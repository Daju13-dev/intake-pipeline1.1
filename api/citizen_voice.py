import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

import firebase_admin
from firebase_admin import credentials, firestore, storage

app = FastAPI()

BUILD_VERSION = "2026-03-23.citizen_voice.1"

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


def _safe_name(name: str) -> str:
    name = (name or "").strip()
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    name = name[:80] if name else "audio"
    return name


@app.get("/api/citizen-voice/health")
async def health():
    return {
        "ok": True,
        "build": BUILD_VERSION,
        "commit": os.environ.get("VERCEL_GIT_COMMIT_SHA")
        or os.environ.get("VERCEL_GITHUB_COMMIT_SHA"),
    }


@app.post("/api/citizen-voice")
async def citizen_voice(
    mission: str = Form(...),
    source_type: str = Form(...),
    region: str = Form(...),
    city: str = Form(...),
    area: Optional[str] = Form(None),
    summary: Optional[str] = Form(None),
    age_range: Optional[str] = Form(None),
    gender: Optional[str] = Form(None),
    occupation: Optional[str] = Form(None),
    consent: str = Form(...),
    audio: UploadFile = File(...),
):
    if (mission or "").strip().lower() != "citizen_voice":
        raise HTTPException(status_code=400, detail="Invalid mission")
    if (source_type or "").strip().lower() != "ground":
        raise HTTPException(status_code=400, detail="Invalid source type")

    try:
        init_firebase()
    except Exception:
        raise HTTPException(status_code=500, detail="Firebase is not configured")

    record_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    if not audio:
        raise HTTPException(status_code=400, detail="Missing audio file")

    raw = await audio.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty audio file")
    if len(raw) > 25 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Audio file is too large (max 25MB)")

    filename = _safe_name(audio.filename or "audio")
    # Keep extension if present; default to .m4a for many mobile recordings.
    ext = ""
    if "." in filename:
        ext = "." + filename.rsplit(".", 1)[1].lower()
        if len(ext) > 6:
            ext = ""
    if ext not in (".mp3", ".m4a", ".wav", ".aac", ".ogg", ""):
        ext = ""
    stored_name = f"voice{ext or '.m4a'}"

    path = f"citizen-voice/{record_id}/{stored_name}"
    blob = _bucket.blob(path)
    content_type = audio.content_type or "application/octet-stream"
    try:
        blob.upload_from_string(raw, content_type=content_type)
        blob.make_public()
    except Exception as e:
        print("[citizen_voice] upload failed:", repr(e))
        raise HTTPException(status_code=500, detail="Upload failed")

    data = {
        "record_id": record_id,
        "created_at": created_at,
        "mission": "citizen_voice",
        "source_type": "ground",
        "region": (region or "").strip(),
        "city": (city or "").strip(),
        "area": (area or "").strip() or None,
        "summary": (summary or "").strip() or None,
        "age_range": (age_range or "").strip() or None,
        "gender": (gender or "").strip() or None,
        "occupation": (occupation or "").strip() or None,
        "consent": str(consent).strip().lower() in ("1", "true", "yes", "on"),
        "media_url": blob.public_url,
        # Future enrichment fields
        "transcript": None,
        "auto_topic": None,
        "sentiment": None,
    }

    try:
        _db.collection("citizen_voice").document(record_id).set(data)
    except Exception as e:
        print("[citizen_voice] firestore write failed:", repr(e))
        raise HTTPException(status_code=500, detail="Database write failed")

    return {"ok": True, "record_id": record_id, "media_url": blob.public_url}

