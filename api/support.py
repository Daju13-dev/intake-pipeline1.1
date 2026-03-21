import json
import os
import random
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

import firebase_admin
from firebase_admin import credentials, firestore, storage

app = FastAPI()

_firebase_app = None
_db = None
_bucket = None


def init_firebase():
    global _firebase_app, _db, _bucket
    if _firebase_app:
        return

    service_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
    bucket_name = os.environ.get("FIREBASE_STORAGE_BUCKET")
    if not service_json or not bucket_name:
        raise RuntimeError("Missing Firebase configuration")

    cred_info = json.loads(service_json)
    cred = credentials.Certificate(cred_info)
    _firebase_app = firebase_admin.initialize_app(cred, {"storageBucket": bucket_name})
    _db = firestore.client()
    _bucket = storage.bucket()


def normalize_code(code: str) -> str:
    code = (code or "").strip().upper()
    code = re.sub(r"[^A-Z0-9]", "", code)
    return code


def wa_link(number_digits: str, text: str) -> str:
    # Use wa.me with digits only. Client will open WhatsApp app if available.
    from urllib.parse import quote

    n = re.sub(r"\D", "", number_digits or "")
    if not n:
        return ""
    return f"https://wa.me/{n}?text={quote(text or '')}"


class SupportAssignPayload(BaseModel):
    message: str = Field(..., min_length=1, max_length=1200)
    prefer_code: Optional[str] = None
    page_url: Optional[str] = None


def rep_to_public(doc_id: str, data: Dict[str, Any]) -> dict:
    return {
        "code": doc_id,
        "name": data.get("name"),
        "email": data.get("email"),
        "whatsapp_number": data.get("whatsapp_number"),
        "photo_url": data.get("photo_url"),
        "active": bool(data.get("active", True)),
    }


@app.post("/api/support/assign")
async def assign(payload: SupportAssignPayload):
    firebase_ok = True
    try:
        init_firebase()
    except Exception:
        firebase_ok = False

    prefer = normalize_code(payload.prefer_code or "")

    rep = None
    rep_code = None

    if firebase_ok:
        if prefer and len(prefer) >= 4:
            try:
                snap = _db.collection("reps").document(prefer).get()
                if snap.exists:
                    data = snap.to_dict() or {}
                    if bool(data.get("active", True)):
                        rep = rep_to_public(prefer, data)
                        rep_code = prefer
            except Exception as e:
                print("[support] firestore error (prefer rep):", repr(e))
                raise HTTPException(
                    status_code=500,
                    detail="Support is temporarily unavailable. Please try again shortly.",
                )

        if not rep:
            try:
                docs = list(
                    _db.collection("reps").where("active", "==", True).limit(50).stream()
                )
                if docs:
                    chosen = random.choice(docs)
                    rep_code = chosen.id
                    rep = rep_to_public(rep_code, chosen.to_dict() or {})
            except Exception as e:
                print("[support] firestore error (pick rep):", repr(e))
                raise HTTPException(
                    status_code=500,
                    detail="Support is temporarily unavailable. Please try again shortly.",
                )

    default_wa = re.sub(r"\D", "", os.environ.get("DEFAULT_SUPPORT_WHATSAPP", ""))
    if not rep:
        # If Firebase is not configured, we still allow WhatsApp launch (ticket creation is skipped).
        # Use DEFAULT_SUPPORT_WHATSAPP when available; otherwise fall back to a safe default.
        if not default_wa:
            default_wa = "233557750104"
        if not default_wa:
            raise HTTPException(
                status_code=503,
                detail="Support chat is temporarily unavailable. Please try again later.",
            )
        rep = {
            "code": "DEFAULT",
            "name": "Support",
            "email": None,
            "whatsapp_number": default_wa,
            "photo_url": None,
            "active": True,
        }
        rep_code = "DEFAULT"

    ticket_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    ticket = {
        "ticket_id": ticket_id,
        "created_at": created_at,
        "channel": "whatsapp",
        "message": payload.message.strip(),
        "rep_code": rep_code,
        "page_url": payload.page_url,
        "status": "open",
    }

    if firebase_ok:
        try:
            _db.collection("support_tickets").document(ticket_id).set(ticket)
        except Exception as e:
            print("[support] firestore error (create ticket):", repr(e))
            # Still allow WhatsApp launch even if ticket storage fails.
            firebase_ok = False

    message_text = (
        "AdwumaTech AI Support\n"
        f"Ticket: {ticket_id[:8].upper()}\n\n"
        f"Message:\n{payload.message.strip()}\n"
    )

    url = wa_link(rep.get("whatsapp_number") or "", message_text)
    return {
        "ok": True,
        "degraded": (not firebase_ok),
        "ticket_id": ticket_id,
        "rep": rep,
        "wa_url": url,
    }
