"""Reservedeler (Bildeler) — TecDoc-fitment for brukerens bil."""
from fastapi import APIRouter, Query

from app.services import tecdoc
from app.services.vegvesenet import parse_basic, vegvesenet_client

router = APIRouter(prefix="/parts", tags=["parts"])


@router.get("/resolve")
async def resolve(
    plate: str = Query(..., min_length=2, max_length=10, description="Skiltnummer"),
):
    """Slå opp bil i Vegvesenet og match den til en TecDoc vehicleId.

    Returnerer best treff + alternativer. Hvis `confident` er false bør appen
    la brukeren bekrefte motorvariant blant `candidates`.
    """
    raw = await vegvesenet_client.lookup_by_plate(plate)
    vehicle = parse_basic(raw)
    result = await tecdoc.resolve_vehicle(vehicle)
    return {"vehicle": vehicle, **result}


@router.get("/vehicles/{vehicle_id}/categories")
async def categories(vehicle_id: int):
    """Hvilke av appens kategorier som har deler tilgjengelig for denne bilen."""
    return {"categories": await tecdoc.available_categories(vehicle_id)}


@router.get("/vehicles/{vehicle_id}/category/{app_category}")
async def parts(vehicle_id: int, app_category: str):
    """Artikler (deler som passer) for én app-kategori, f.eks. «olje»."""
    items = await tecdoc.parts_for_category(vehicle_id, app_category)
    return {"category": app_category, "count": len(items), "articles": items}


@router.get("/articles/{article_id}/specifications")
async def specifications(article_id: int):
    """Tekniske spesifikasjoner for én artikkel. Kun for detaljvisning --
    kalles aldri fra listevisninger. Tom liste (ikke feil) hvis katalogen
    ikke har spesifikasjoner for denne artikkelen."""
    specs = await tecdoc.specifications_for_article(article_id)
    return {"articleId": article_id, "specifications": specs}
