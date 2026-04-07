from fastapi import APIRouter, Query

from app.services.vegvesenet import vegvesenet_client

router = APIRouter(prefix="/cars", tags=["cars"])


@router.get("/lookup")
async def lookup_car(
    plate: str = Query(..., min_length=2, max_length=10, description="Skiltnummer"),
):
    """Slå opp et kjøretøy fra Vegvesenet basert på skiltnummer."""
    return await vegvesenet_client.lookup_by_plate(plate)
