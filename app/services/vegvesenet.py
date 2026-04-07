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
