from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.anthropic_chat import chat_with_mechanic
from app.services.rate_limit import chat_rate_limiter

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatMessage(BaseModel):
    role: str  # 'user' eller 'assistant'
    content: str


class ChatRequest(BaseModel):
    vehicle: dict[str, Any] = Field(default_factory=dict)
    history: list[ChatMessage] = Field(default_factory=list)
    message: str
    user_name: str | None = None
    device_id: str | None = None
    is_pro: bool = False


class ChatResponse(BaseModel):
    reply: str
    used_count: int = 0
    limit: int = 0
    remaining: int = 0


class ChatLimitResponse(BaseModel):
    used_count: int
    limit: int
    remaining: int


@router.get("/limit", response_model=ChatLimitResponse)
async def get_limit(device_id: str):
    used = chat_rate_limiter.get_count(device_id)
    return ChatLimitResponse(
        used_count=used,
        limit=chat_rate_limiter.FREE_LIMIT_PER_MONTH,
        remaining=chat_rate_limiter.remaining(device_id),
    )


@router.post("/mechanic", response_model=ChatResponse)
async def mechanic(req: ChatRequest):
    """Spør AI-mekanikeren om bilen."""
    # Rate-limit for free brukere
    if not req.is_pro:
        if not req.device_id:
            raise HTTPException(
                status_code=400,
                detail="device_id er påkrevd for free brukere",
            )
        if not chat_rate_limiter.can_use(req.device_id):
            raise HTTPException(
                status_code=429,
                detail=(
                    "Du har brukt opp dine "
                    f"{chat_rate_limiter.FREE_LIMIT_PER_MONTH} gratis "
                    "AI-spørsmål denne måneden. Oppgrader til Pro for ubegrenset."
                ),
            )

    reply = await chat_with_mechanic(
        vehicle=req.vehicle,
        history=[m.model_dump() for m in req.history],
        user_message=req.message,
        user_name=req.user_name,
    )

    if not req.is_pro and req.device_id:
        chat_rate_limiter.increment(req.device_id)

    used = (
        chat_rate_limiter.get_count(req.device_id)
        if req.device_id and not req.is_pro
        else 0
    )
    return ChatResponse(
        reply=reply,
        used_count=used,
        limit=chat_rate_limiter.FREE_LIMIT_PER_MONTH if not req.is_pro else 0,
        remaining=chat_rate_limiter.remaining(req.device_id)
        if req.device_id and not req.is_pro
        else 999,
    )
