import base64
import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

import firebase_admin
from firebase_admin import credentials, firestore, storage

app = FastAPI()

BUILD_VERSION = "2026-03-15.reps.1"

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


def require_admin(req: Request):
    token = req.headers.get("x-admin-token") or ""
    expected = os.environ.get("STAFF_ADMIN_TOKEN") or ""
    if not expected:
        # If not configured, always deny admin actions.
        raise HTTPException(status_code=500, detail="Admin is not configured")
    if token.strip() != expected.strip():
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/api/reps/health")
async def reps_health():
    return {
        "ok": True,
        "build": BUILD_VERSION,
        "commit": os.environ.get("VERCEL_GIT_COMMIT_SHA")
        or os.environ.get("VERCEL_GITHUB_COMMIT_SHA"),
    }


def decode_data_url(data_url: str) -> bytes:
    if "," in data_url:
        data_url = data_url.split(",", 1)[1]
    return base64.b64decode(data_url)


def normalize_code(code: str) -> str:
    code = (code or "").strip().upper()
    code = re.sub(r"[^A-Z0-9]", "", code)
    return code


def normalize_whatsapp(raw: str) -> str:
    # Store as digits only (E.164 without +). Example: 233557750104
    digits = re.sub(r"\D", "", (raw or ""))
    # Convenience: convert Ghana local "0XXXXXXXXX" to "233XXXXXXXXX"
    if len(digits) == 10 and digits.startswith("0"):
        digits = "233" + digits[1:]
    if len(digits) < 10 or len(digits) > 15:
        raise ValueError("Invalid WhatsApp number")
    return digits


class RepCreatePayload(BaseModel):
    code: Optional[str] = Field(default=None, description="Optional custom code")
    name: str = Field(..., min_length=2, max_length=80)
    email: str = Field(..., min_length=5, max_length=120)
    whatsapp_number: str = Field(..., min_length=10, max_length=24, description="E.164 or local digits")
    image_data_url: Optional[str] = Field(default=None, description="data:image/...;base64,...")
    active: bool = True


class RepUpdatePayload(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=80)
    email: Optional[str] = Field(default=None, min_length=5, max_length=120)
    whatsapp_number: Optional[str] = Field(default=None, min_length=10, max_length=24)
    image_data_url: Optional[str] = None
    active: Optional[bool] = None


def rep_to_public(doc_id: str, data: dict) -> dict:
    return {
        "code": doc_id,
        "name": data.get("name"),
        "email": data.get("email"),
        "whatsapp_number": data.get("whatsapp_number"),
        "photo_url": data.get("photo_url"),
        "active": bool(data.get("active", True)),
    }


@app.get("/api/reps/{code}")
async def get_rep(code: str):
    try:
        init_firebase()
    except Exception:
        raise HTTPException(status_code=500, detail="Firebase is not configured")

    code = normalize_code(code)
    # Codes are generated/accepted as 6-12 chars (letters/numbers).
    if len(code) < 6 or len(code) > 12:
        raise HTTPException(status_code=400, detail="Code must be 6-12 letters/numbers")

    try:
        snap = _db.collection("reps").document(code).get()
    except Exception as e:
        print("[reps] firestore error (get_rep):", repr(e))
        raise HTTPException(
            status_code=500,
            detail="Firestore is not set up yet. In Firebase Console, create Firestore Database and try again.",
        )
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Representative not found")

    data = snap.to_dict() or {}
    return {"ok": True, "rep": rep_to_public(code, data)}


@app.get("/api/reps")
async def list_reps(active: Optional[bool] = True):
    try:
        init_firebase()
    except Exception:
        raise HTTPException(status_code=500, detail="Firebase is not configured")

    try:
        q = _db.collection("reps")
        if active is not None:
            q = q.where("active", "==", bool(active))

        reps = []
        for doc in q.limit(50).stream():
            reps.append(rep_to_public(doc.id, doc.to_dict() or {}))
        return {"ok": True, "reps": reps}
    except Exception as e:
        print("[reps] firestore error (list_reps):", repr(e))
        raise HTTPException(
            status_code=500,
            detail="Firestore is not set up yet. In Firebase Console, create Firestore Database and try again.",
        )


@app.get("/api/reps/all")
async def list_reps_all(req: Request):
    require_admin(req)
    try:
        init_firebase()
    except Exception:
        raise HTTPException(status_code=500, detail="Firebase is not configured")

    try:
        reps = []
        for doc in _db.collection("reps").limit(200).stream():
            reps.append(rep_to_public(doc.id, doc.to_dict() or {}))
        return {"ok": True, "reps": reps}
    except Exception as e:
        print("[reps] firestore error (list_reps_all):", repr(e))
        raise HTTPException(
            status_code=500,
            detail="Firestore is not set up yet. In Firebase Console, create Firestore Database and try again.",
        )


@app.post("/api/reps")
async def create_rep(req: Request, payload: RepCreatePayload):
    require_admin(req)
    try:
        init_firebase()
    except Exception:
        raise HTTPException(status_code=500, detail="Firebase is not configured")

    code = normalize_code(payload.code) if payload.code else ""
    if not code:
        code = normalize_code(uuid.uuid4().hex[:8])

    if len(code) < 6 or len(code) > 12:
        raise HTTPException(status_code=400, detail="Code must be 6-12 letters/numbers")

    try:
        wa = normalize_whatsapp(payload.whatsapp_number)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid WhatsApp number")

    photo_url = None
    if payload.image_data_url:
        try:
            img = decode_data_url(payload.image_data_url)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid image")
        if len(img) > 650_000:
            raise HTTPException(status_code=400, detail="Image too large")

        blob = _bucket.blob(f"reps/{code}.jpg")
        blob.upload_from_string(img, content_type="image/jpeg")
        blob.make_public()
        photo_url = blob.public_url

    now = datetime.now(timezone.utc).isoformat()
    data = {
        "code": code,
        "name": payload.name.strip(),
        "email": payload.email.strip(),
        "whatsapp_number": wa,
        "photo_url": photo_url,
        "active": bool(payload.active),
        "created_at": now,
        "updated_at": now,
    }

    _db.collection("reps").document(code).set(data, merge=True)
    return {"ok": True, "rep": rep_to_public(code, data)}


@app.patch("/api/reps/{code}")
async def update_rep(code: str, req: Request, payload: RepUpdatePayload):
    require_admin(req)
    try:
        init_firebase()
    except Exception:
        raise HTTPException(status_code=500, detail="Firebase is not configured")

    code = normalize_code(code)
    if len(code) < 6:
        raise HTTPException(status_code=400, detail="Invalid code")

    ref = _db.collection("reps").document(code)
    snap = ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Representative not found")

    patch = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if payload.name is not None:
        patch["name"] = payload.name.strip()
    if payload.email is not None:
        patch["email"] = payload.email.strip()
    if payload.whatsapp_number is not None:
        try:
            patch["whatsapp_number"] = normalize_whatsapp(payload.whatsapp_number)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid WhatsApp number")
    if payload.active is not None:
        patch["active"] = bool(payload.active)

    if payload.image_data_url:
        try:
            img = decode_data_url(payload.image_data_url)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid image")
        if len(img) > 650_000:
            raise HTTPException(status_code=400, detail="Image too large")
        blob = _bucket.blob(f"reps/{code}.jpg")
        blob.upload_from_string(img, content_type="image/jpeg")
        blob.make_public()
        patch["photo_url"] = blob.public_url

    ref.set(patch, merge=True)
    data = (ref.get().to_dict() or {})
    return {"ok": True, "rep": rep_to_public(code, data)}
