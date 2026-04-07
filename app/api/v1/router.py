from fastapi import APIRouter

from app.api.v1.endpoints import cars

api_router = APIRouter()
api_router.include_router(cars.router)
