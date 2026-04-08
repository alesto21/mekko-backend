"""Skann kvitteringer / service-dokumenter med Claude vision."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.anthropic_vision import extract_receipt_data
from app.services.rate_limit import scan_rate_limiter

router = APIRouter(prefix="/scan", tags=["scan"])


class ScanReceiptRequest(BaseModel):
    image_base64: str = Field(..., description="Base64-encoded image (med eller uten data-URL-prefix)")
    media_type: str = Field("image/jpeg", description="image/jpeg, image/png, image/webp, image/gif")
    device_id: str | None = None
    is_pro: bool = False


class ScanReceiptResponse(BaseModel):
    date: str | None = None
    mileage_km: int | None = None
    workshop: str | None = None
    cost_nok: float | None = None
    type: str = "annet"
    notes: str | None = None
    confidence: str = "medium"
    is_receipt: bool = True
    used_count: int = 0
    limit: int = 0
    remaining: int = 0


class ScanLimitResponse(BaseModel):
    used_count: int
    limit: int
    remaining: int


@router.get("/limit", response_model=ScanLimitResponse)
async def get_scan_limit(device_id: str):
    used = scan_rate_limiter.get_count(device_id)
    return ScanLimitResponse(
        used_count=used,
        limit=scan_rate_limiter.FREE_LIMIT_PER_MONTH,
        remaining=scan_rate_limiter.remaining(device_id),
    )


@router.post("/receipt", response_model=ScanReceiptResponse)
async def scan_receipt(req: ScanReceiptRequest):
    """Send et bilde av en kvittering og få strukturert service-data tilbake."""
    # Rate-limit free brukere
    if not req.is_pro:
        if not req.device_id:
            raise HTTPException(
                status_code=400,
                detail="device_id er påkrevd for free brukere",
            )
        if not scan_rate_limiter.can_use(req.device_id):
            raise HTTPException(
                status_code=429,
                detail=(
                    "Du har brukt opp dine "
                    f"{scan_rate_limiter.FREE_LIMIT_PER_MONTH} gratis "
                    "kvittering-skanninger denne måneden. Oppgrader til Pro for ubegrenset."
                ),
            )

    result = await extract_receipt_data(
        image_base64=req.image_base64,
        media_type=req.media_type,
    )

    # Tell bare som brukt hvis det faktisk var en kvittering — ikke straff brukeren
    # for å sende noe annet ved en feil
    if not req.is_pro and req.device_id and result.get("is_receipt"):
        scan_rate_limiter.increment(req.device_id)

    used = (
        scan_rate_limiter.get_count(req.device_id)
        if req.device_id and not req.is_pro
        else 0
    )
    return ScanReceiptResponse(
        date=result.get("date"),
        mileage_km=result.get("mileage_km"),
        workshop=result.get("workshop"),
        cost_nok=result.get("cost_nok"),
        type=result.get("type", "annet"),
        notes=result.get("notes"),
        confidence=result.get("confidence", "medium"),
        is_receipt=result.get("is_receipt", True),
        used_count=used,
        limit=scan_rate_limiter.FREE_LIMIT_PER_MONTH if not req.is_pro else 0,
        remaining=scan_rate_limiter.remaining(req.device_id)
        if req.device_id and not req.is_pro
        else 999,
    )
