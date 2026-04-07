import sys
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.config import settings

router = APIRouter(prefix="/feedback", tags=["feedback"])


class FeedbackRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    subject: str | None = Field(None, max_length=200)
    contact_name: str | None = Field(None, max_length=100)
    contact_email: str | None = Field(None, max_length=200)
    app_version: str | None = Field(None, max_length=50)


class FeedbackResponse(BaseModel):
    ok: bool
    message: str


def _category_color(subject: str | None) -> int:
    """Returner Discord embed-farge basert på subject-prefiks."""
    if not subject:
        return 0x5865F2  # blurple
    s = subject.lower()
    if "bug" in s or "feil" in s:
        return 0xED4245  # rød
    if "forslag" in s or "idé" in s or "ide" in s:
        return 0xFEE75C  # gul
    if "spørsmål" in s or "sporsmal" in s:
        return 0x5865F2  # blå
    return 0x57F287  # grønn (generelt)


async def _send_to_discord(req: FeedbackRequest, timestamp: str) -> None:
    """Send tilbakemelding som embed til Discord webhook hvis URL er satt."""
    url = settings.discord_webhook_url
    if not url:
        return

    fields = []
    if req.contact_name:
        fields.append({"name": "Navn", "value": req.contact_name, "inline": True})
    if req.contact_email:
        fields.append(
            {"name": "Epost", "value": req.contact_email, "inline": True}
        )
    if req.app_version:
        fields.append(
            {"name": "Versjon", "value": req.app_version, "inline": True}
        )

    embed = {
        "title": req.subject or "Ny tilbakemelding",
        "description": req.message,
        "color": _category_color(req.subject),
        "fields": fields,
        "footer": {"text": "MinBil feedback"},
        "timestamp": timestamp,
    }
    payload = {"embeds": [embed]}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, json=payload)
    except Exception as exc:  # ikke la Discord-feil bryte feedback-endpointen
        print(f"⚠️  Feilet å sende til Discord: {exc}", flush=True)


@router.post("", response_model=FeedbackResponse)
async def submit_feedback(req: FeedbackRequest):
    """Mottar tilbakemelding fra MinBil-appen.

    Logger til stdout (synlig i Railway-logger) og sender til Discord webhook
    hvis DISCORD_WEBHOOK_URL er satt som env-var.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    sep = "=" * 60
    print(
        f"\n{sep}\n"
        f"📨 NY TILBAKEMELDING ({timestamp})\n"
        f"{sep}\n"
        f"Fra: {req.contact_name or '(anonym)'} <{req.contact_email or '(ingen epost)'}>\n"
        f"Subject: {req.subject or '(ingen subject)'}\n"
        f"Versjon: {req.app_version or '(ukjent)'}\n"
        f"{sep}\n"
        f"{req.message}\n"
        f"{sep}\n",
        flush=True,
    )

    await _send_to_discord(req, timestamp)

    return FeedbackResponse(
        ok=True,
        message="Takk for tilbakemeldingen!",
    )
