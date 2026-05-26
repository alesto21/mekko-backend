"""Klient mot Statens Vegvesen sin Kjøretøyopplysninger-API."""
import httpx
from fastapi import HTTPException

from app.core.config import settings


class VegvesenetClient:
    def __init__(self) -> None:
        self.base_url = settings.vegvesenet_base_url
        self.api_key = settings.vegvesenet_api_key

    async def lookup_by_plate(self, plate: str) -> dict:
        """Slå opp et kjøretøy basert på skiltnummer.

        Returnerer rå JSON-respons fra Vegvesenet.
        Reiser HTTPException ved feil.
        """
        if not self.api_key:
            raise HTTPException(
                status_code=500,
                detail="VEGVESENET_API_KEY mangler i miljøvariabler",
            )
        normalized = plate.upper().replace(" ", "").strip()
        if not normalized:
            raise HTTPException(status_code=400, detail="Tomt skiltnummer")

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(
                    self.base_url,
                    params={"kjennemerke": normalized},
                    headers={"SVV-Authorization": f"Apikey {self.api_key}"},
                )
            except httpx.RequestError as exc:
                raise HTTPException(
                    status_code=503,
                    detail=f"Klarte ikke kontakte Vegvesenet: {exc}",
                ) from exc

        if response.status_code == 404:
            raise HTTPException(
                status_code=404, detail=f"Ingen bil funnet med skilt {normalized}"
            )
        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Vegvesenet returnerte {response.status_code}",
            )

        return response.json()


vegvesenet_client = VegvesenetClient()


def parse_basic(raw: dict) -> dict:
    """Plukk ut feltene som trengs for TecDoc-matching fra Vegvesen-rådata."""
    lst = raw.get("kjoretoydataListe") or []
    if not lst:
        raise HTTPException(status_code=404, detail="Tom respons fra Vegvesenet")
    v = lst[0]
    td = (
        v.get("godkjenning", {})
        .get("tekniskGodkjenning", {})
        .get("tekniskeData", {})
    )
    gen = td.get("generelt", {})
    merke_liste = gen.get("merke") or []
    merke = merke_liste[0].get("merke") if merke_liste else None
    handel = gen.get("handelsbetegnelse") or []
    modell = handel[0] if handel else None

    motor_liste = td.get("motorOgDrivverk", {}).get("motor") or []
    motor = motor_liste[0] if motor_liste else {}
    slagvolum = motor.get("slagvolum")
    drivstoff = None
    effekt_kw = None
    dl = motor.get("drivstoff") or []
    if dl:
        drivstoff = (dl[0].get("drivstoffKode") or {}).get("kodeNavn")
        effekt_kw = dl[0].get("maksNettoEffekt")

    forste = (
        v.get("forstegangsregistrering", {})
        .get("registrertForstegangNorgeDato")
    )
    return {
        "plate": (v.get("kjoretoyId") or {}).get("kjennemerke"),
        "vin": (v.get("kjoretoyId") or {}).get("understellsnummer"),
        "merke": merke,
        "modell": modell,
        "slagvolum": int(slagvolum) if slagvolum else None,
        "effektKw": float(effekt_kw) if effekt_kw else None,
        "drivstoff": drivstoff,
        "forsteRegistrert": forste,
    }
