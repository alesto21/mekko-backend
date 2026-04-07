from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.anthropic_chat import chat_with_mechanic

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatMessage(BaseModel):
    role: str  # 'user' eller 'assistant'
    content: str


class ChatRequest(BaseModel):
    vehicle: dict[str, Any] = Field(default_factory=dict)
    history: list[ChatMessage] = Field(default_factory=list)
    message: str
    user_name: str | None = None


class ChatResponse(BaseModel):
    reply: str


@router.post("/mechanic", response_model=ChatResponse)
async def mechanic(req: ChatRequest):
    """Spør AI-mekanikeren om bilen."""
    reply = await chat_with_mechanic(
        vehicle=req.vehicle,
        history=[m.model_dump() for m in req.history],
        user_message=req.message,
        user_name=req.user_name,
    )
    return ChatResponse(reply=reply)
