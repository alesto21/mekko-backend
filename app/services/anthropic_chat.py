"""AI-mekaniker — Anthropic Claude med bilkontekst."""
import httpx
from fastapi import HTTPException

from app.core.config import settings


SYSTEM_PROMPT = """Du er en erfaren norsk bilmekaniker som hjelper bileiere via en mobilapp som heter MinBil.

VIKTIGE REGLER:
- Svar ALLTID på norsk (bokmål)
- Vær konkret, kort og praktisk — ikke generisk
- Tilpass svaret til den spesifikke bilen brukeren spør om (merke, modell, årsmodell, motor)
- Hvis du ikke vet noe sikkert, si det rett ut. Ikke gjett.
- Ved alvorlige feil (motor, bremser, sikkerhet): anbefal å oppsøke verksted
- Estimer priser i NOK når det er relevant (bruk gjennomsnittlige norske verkstedpriser)
- Hold svar under 250 ord med mindre brukeren ber om mer

FORMATERING (KRITISK):
- IKKE bruk markdown-formatering (ingen #, ##, **bold**, *italic*, eller backticks)
- Skriv vanlig tekst med vanlige norske setninger
- Bruk bindestrek (-) eller bullet (•) for lister hvis det er nødvendig
- Bruk linjeskift for å dele opp avsnitt
- Skriv som du ville snakket til en kunde i resepsjonen, ikke som en wiki-artikkel

DU SKAL IKKE:
- Anbefale at brukeren reparerer alvorlige feil selv hvis de mangler kompetanse
- Gi medisinske eller juridiske råd
- Diskutere ting som ikke har med bilen å gjøre
"""


def _build_user_context(vehicle: dict) -> str:
    """Bygger en kort kontekst-streng om bilen som inkluderes i system-prompten."""
    parts = []
    if vehicle.get("merke") or vehicle.get("modell"):
        merke = (vehicle.get("merke") or "").strip()
        modell = (vehicle.get("modell") or "").strip()
        parts.append(f"Bil: {merke} {modell}".strip())
    if vehicle.get("aarsmodell"):
        parts.append(f"Årsmodell: {vehicle['aarsmodell']}")
    if vehicle.get("drivstoff"):
        parts.append(f"Drivstoff: {vehicle['drivstoff']}")
    if vehicle.get("slagvolum"):
        parts.append(f"Motor: {vehicle['slagvolum']} cc")
    if vehicle.get("effektKw"):
        hk = round(vehicle["effektKw"] * 1.36)
        parts.append(f"Effekt: {hk} hk ({vehicle['effektKw']} kW)")
    if vehicle.get("girkasse"):
        parts.append(f"Girkasse: {vehicle['girkasse']}")
    if vehicle.get("euroKlasse"):
        parts.append(f"Euro-klasse: {vehicle['euroKlasse']}")
    if vehicle.get("plate"):
        parts.append(f"Skilt: {vehicle['plate']}")
    return "\n".join(parts) if parts else "Ingen bilinformasjon oppgitt."


async def chat_with_mechanic(
    vehicle: dict,
    history: list[dict],
    user_message: str,
) -> str:
    """Send chat-melding til Claude og returner svaret.

    history: liste av {role: 'user'|'assistant', content: str}
    """
    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=500,
            detail="ANTHROPIC_API_KEY mangler i miljøvariabler",
        )

    car_context = _build_user_context(vehicle)
    system = f"{SYSTEM_PROMPT}\n\n--- BILKONTEKST ---\n{car_context}\n--- SLUTT KONTEKST ---"

    messages = []
    for msg in history:
        if msg.get("role") in ("user", "assistant") and msg.get("content"):
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_message})

    payload = {
        "model": settings.anthropic_model,
        "max_tokens": settings.anthropic_max_tokens,
        "system": system,
        "messages": messages,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
            )
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Klarte ikke kontakte Anthropic: {exc}",
            ) from exc

    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Anthropic returnerte {response.status_code}: {response.text[:200]}",
        )

    data = response.json()
    content_blocks = data.get("content", [])
    if not content_blocks:
        return "Beklager, jeg fikk ikke noe svar fra AI-en. Prøv igjen."
    return content_blocks[0].get("text", "")
