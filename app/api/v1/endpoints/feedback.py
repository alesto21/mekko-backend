import logging
from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/feedback", tags=["feedback"])

logger = logging.getLogger("minbil.feedback")
logger.setLevel(logging.INFO)


class FeedbackRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    subject: str | None = Field(None, max_length=200)
    contact_name: str | None = Field(None, max_length=100)
    contact_email: str | None = Field(None, max_length=200)
    app_version: str | None = Field(None, max_length=50)


class FeedbackResponse(BaseModel):
    ok: bool
    message: str


@router.post("", response_model=FeedbackResponse)
async def submit_feedback(req: FeedbackRequest):
    """Mottar tilbakemelding fra MinBil-appen.

    Foreløpig logges tilbakemeldingen til stdout (synlig i Railway-loggene).
    Senere: forward til epost via Resend eller lignende.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    sep = "=" * 60
    logger.info(
        "\n%s\n📨 NY TILBAKEMELDING (%s)\n%s\n"
        "Fra: %s <%s>\n"
        "Subject: %s\n"
        "Versjon: %s\n"
        "%s\n"
        "%s\n"
        "%s",
        sep,
        timestamp,
        sep,
        req.contact_name or "(anonym)",
        req.contact_email or "(ingen epost)",
        req.subject or "(ingen subject)",
        req.app_version or "(ukjent)",
        sep,
        req.message,
        sep,
    )
    return FeedbackResponse(
        ok=True,
        message="Takk for tilbakemeldingen!",
    )
