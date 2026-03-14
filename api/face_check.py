import os
import json
import base64
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import firebase_admin
from firebase_admin import credentials, firestore, storage

app = FastAPI()

class FaceCheckPayload(BaseModel):
    selfie_front: str
    selfie_turn: str
    network: Optional[str] = None
    momo_number: Optional[str] = None

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


def decode_data_url(data_url: str) -> bytes:
    if "," in data_url:
        data_url = data_url.split(",", 1)[1]
    return base64.b64decode(data_url)


@app.post("/api/face-check")
async def face_check(payload: FaceCheckPayload):
    try:
        init_firebase()
    except Exception:
        raise HTTPException(status_code=500, detail="Firebase is not configured")

    record_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    try:
        front_bytes = decode_data_url(payload.selfie_front)
        turn_bytes = decode_data_url(payload.selfie_turn)

        front_path = f"face-check/{record_id}/selfie_front.jpg"
        turn_path = f"face-check/{record_id}/selfie_turn.jpg"

        front_blob = _bucket.blob(front_path)
        turn_blob = _bucket.blob(turn_path)

        front_blob.upload_from_string(front_bytes, content_type="image/jpeg")
        turn_blob.upload_from_string(turn_bytes, content_type="image/jpeg")

        front_blob.make_public()
        turn_blob.make_public()

        data = {
            "record_id": record_id,
            "created_at": created_at,
            "network": payload.network,
            "momo_number": payload.momo_number,
            "selfie_front_url": front_blob.public_url,
            "selfie_turn_url": turn_blob.public_url,
        }

        _db.collection("face_checks").document(record_id).set(data)

        return {"ok": True, "record_id": record_id, "selfies": {
            "front": front_blob.public_url,
            "turn": turn_blob.public_url
        }}

    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Upload failed: {exc}")
