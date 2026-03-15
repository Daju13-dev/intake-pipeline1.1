import os
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


app = FastAPI()


SYSTEM_PROMPT = (
    "You are AdwumaTech AI's helpful support assistant for the Digital Safety Initiative.\n"
    "Tone: warm, concise, professional.\n"
    "Goal: answer FAQs and guide users through: Participate → Mission → Face Check → Claim Reward.\n"
    "Safety:\n"
    "- Do not ask for or request sensitive personal data (ID numbers, full addresses, selfies, passwords, OTPs).\n"
    "- If the user reports imminent danger or physical harm, advise them to contact local emergency services.\n"
    "- If the user asks about rewards, explain the steps and that network + 10-digit number is used for payout.\n"
    "- If the user asks to report abuse (Safe Space), explain it's prioritized and may be escalated.\n"
    "If you are unsure, ask one short clarifying question.\n"
)


class ChatMessage(BaseModel):
    role: str = Field(..., description="user|assistant")
    content: str = Field(..., min_length=1, max_length=1200)


class ChatPayload(BaseModel):
    message: str = Field(..., min_length=1, max_length=1200)
    history: Optional[List[ChatMessage]] = None


def _extract_output_text(data: Dict[str, Any]) -> str:
    # Responses API returns output messages that contain output_text chunks.
    for item in data.get("output", []) or []:
        if item.get("type") != "message":
            continue
        if item.get("role") != "assistant":
            continue
        for part in item.get("content", []) or []:
            if part.get("type") == "output_text" and part.get("text"):
                return str(part.get("text"))
    # Fallbacks (defensive)
    if isinstance(data.get("output_text"), str) and data["output_text"].strip():
        return data["output_text"].strip()
    return ""


@app.post("/api/chat")
async def chat(payload: ChatPayload):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OpenAI is not configured")

    model = os.environ.get("OPENAI_MODEL", "gpt-5-mini")

    # Keep small, safe context. Client may send history; we cap it.
    input_items: List[Dict[str, Any]] = [
        {
            "role": "system",
            "content": [{"type": "input_text", "text": SYSTEM_PROMPT}],
        }
    ]

    if payload.history:
        for m in payload.history[-8:]:
            role = (m.role or "").strip().lower()
            if role not in ("user", "assistant"):
                continue
            text = (m.content or "").strip()
            if not text:
                continue
            input_items.append(
                {"role": role, "content": [{"type": "input_text", "text": text[:1200]}]}
            )

    user_text = payload.message.strip()
    input_items.append(
        {"role": "user", "content": [{"type": "input_text", "text": user_text[:1200]}]}
    )

    req_json: Dict[str, Any] = {
        "model": model,
        "input": input_items,
        "max_output_tokens": 260,
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=req_json,
            )
    except Exception:
        raise HTTPException(status_code=502, detail="AI service is unreachable")

    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail="AI service error")

    data = resp.json()
    reply = _extract_output_text(data).strip()
    if not reply:
        raise HTTPException(status_code=502, detail="Empty AI response")

    return {"ok": True, "reply": reply}

