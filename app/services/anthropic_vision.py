"""Claude Vision — analyser bilder av kvitteringer fra norske verksteder."""
import base64
import json
import re

import httpx
from fastapi import HTTPException

from app.core.config import settings


# Service-typer som matcher Flutter-appens enum (ServiceType i main.dart)
ALLOWED_TYPES = [
    "oljeskift",
    "filterskift",
    "bremser",
    "dekkskift",
    "euKontroll",
    "fullService",
    "reparasjon",
    "annet",
]


VISION_PROMPT = """Du er en assistent som analyserer norske verksted-kvitteringer og servicebok-bilder.

Brukeren har sendt et bilde av en kvittering eller servicedokument fra et norsk bilverksted.
Din jobb er å hente ut strukturert informasjon og returnere den som JSON.

VIKTIG — RETURNER KUN GYLDIG JSON, ingen forklaring, ingen markdown, ingen tekst utenfor objektet.

Felter du skal hente ut:

{
  "date": "YYYY-MM-DD" eller null hvis ikke synlig,
  "mileage_km": heltall (kilometerstand) eller null,
  "workshop": navn på verksted som streng eller null,
  "cost_nok": tall (totalbeløp i NOK inkl. mva) eller null,
  "type": en av ["oljeskift","filterskift","bremser","dekkskift","euKontroll","fullService","reparasjon","annet"],
  "notes": kort beskrivelse av jobben (maks 120 tegn) som streng eller null,
  "confidence": "high" | "medium" | "low" — hvor sikker du er på utlesingen,
  "is_receipt": true hvis bildet faktisk er en bil-relatert kvittering, false ellers
}

REGLER FOR FELTENE:

date:
- Norsk datoformat er ofte DD.MM.YYYY eller DD.MM.YY — konverter til YYYY-MM-DD
- Hvis bare måned/år er synlig, sett dag til 01
- Hvis du ikke ser noen dato, returner null

mileage_km:
- Se etter "Km", "Kilometer", "Kjørelengde", "Stand"
- Returner som heltall (uten mellomrom eller punktum)
- Hvis ikke synlig, returner null

workshop:
- Navnet på bedriften øverst på kvitteringen (Mekonomen, Bilxtra, Møller Bil, osv)
- Inkluder gjerne sted hvis det står ("Mekonomen Hønefoss")
- Hvis ikke synlig, returner null

cost_nok:
- Totalbeløp inkl. mva i norske kroner
- Returner som tall, ikke streng (1250.50, ikke "1 250,50 kr")
- Hvis flere totaler synlige, velg "Å betale" eller "Totalt"

type:
- Gjett basert på hva som ble utført. Bruk disse reglene:
  - oljeskift: oljeskift, motorolje, oljefilter
  - filterskift: pollenfilter, luftfilter, drivstoffilter
  - bremser: bremseklosser, bremseskiver, bremsevæske
  - dekkskift: dekkbytte, dekkskift, sesong-skifte, hjulskift
  - euKontroll: EU-kontroll, periodisk kjøretøykontroll, PKK
  - fullService: full service, stor service, service-pakke
  - reparasjon: spesifikk reparasjon (elektronikk, motor, gir, koblings)
  - annet: alt annet
- Hvis flere ting ble gjort, velg den mest fremtredende eller "fullService"

notes:
- Kort sammendrag av hva som ble gjort, maks 120 tegn
- Eksempel: "Oljeskift, nytt oljefilter, bremsevæske byttet"
- Hvis du ikke kan oppsummere, returner null

confidence:
- "high" = du er sikker på alle hovedfeltene (dato, beløp, verksted)
- "medium" = noen felter er gjettet eller usikre
- "low" = bildet er uklart eller mangler mye informasjon

is_receipt:
- false hvis bildet ikke er en kvittering/service-dokument (f.eks. selfie, bil-bilde, mat, annet)
- true ellers

EKSEMPEL OUTPUT:
{"date":"2024-03-15","mileage_km":85420,"workshop":"Mekonomen Hønefoss","cost_nok":1850.00,"type":"oljeskift","notes":"Oljeskift, nytt oljefilter","confidence":"high","is_receipt":true}
"""


def _extract_json(text: str) -> dict:
    """Trekk ut første gyldige JSON-objekt fra tekst (Claude kan av og til legge til whitespace)."""
    text = text.strip()
    # Hvis Claude pakker i ```json ... ``` strip det
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Forsøk å finne det første {...}-blokken
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"Klarte ikke parse Claude-respons som JSON: {exc}",
                ) from exc
        raise HTTPException(
            status_code=502,
            detail="Claude returnerte ikke gyldig JSON",
        )


def _normalize_result(parsed: dict) -> dict:
    """Sørg for at alle felter har riktige typer og at type-enumen er gyldig."""
    result = {
        "date": parsed.get("date"),
        "mileage_km": parsed.get("mileage_km"),
        "workshop": parsed.get("workshop"),
        "cost_nok": parsed.get("cost_nok"),
        "type": parsed.get("type") or "annet",
        "notes": parsed.get("notes"),
        "confidence": parsed.get("confidence") or "medium",
        "is_receipt": bool(parsed.get("is_receipt", True)),
    }

    # Valider type-enum
    if result["type"] not in ALLOWED_TYPES:
        result["type"] = "annet"

    # Konverter cost til float hvis mulig
    if result["cost_nok"] is not None:
        try:
            result["cost_nok"] = float(result["cost_nok"])
        except (TypeError, ValueError):
            result["cost_nok"] = None

    # Konverter mileage til int
    if result["mileage_km"] is not None:
        try:
            result["mileage_km"] = int(result["mileage_km"])
        except (TypeError, ValueError):
            result["mileage_km"] = None

    return result


async def extract_receipt_data(
    image_base64: str,
    media_type: str = "image/jpeg",
) -> dict:
    """Send et bilde til Claude vision og returner strukturert kvittering-data.

    image_base64: rå base64-streng (uten data:image-prefix)
    media_type: image/jpeg, image/png, image/webp eller image/gif
    """
    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=500,
            detail="ANTHROPIC_API_KEY mangler i miljøvariabler",
        )

    # Strip eventuell data-URL-prefix
    if image_base64.startswith("data:"):
        # f.eks. "data:image/jpeg;base64,/9j/4AAQ..."
        header, _, payload = image_base64.partition(",")
        image_base64 = payload
        m = re.match(r"data:(image/\w+);base64", header)
        if m:
            media_type = m.group(1)

    if media_type not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
        raise HTTPException(
            status_code=400,
            detail=f"Ugyldig bildeformat: {media_type}",
        )

    payload = {
        "model": settings.anthropic_model,
        "max_tokens": 800,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_base64,
                        },
                    },
                    {
                        "type": "text",
                        "text": VISION_PROMPT,
                    },
                ],
            }
        ],
    }

    async with httpx.AsyncClient(timeout=90.0) as client:
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
        raise HTTPException(
            status_code=502,
            detail="Tomt svar fra Claude vision",
        )

    raw_text = content_blocks[0].get("text", "")
    parsed = _extract_json(raw_text)
    return _normalize_result(parsed)
