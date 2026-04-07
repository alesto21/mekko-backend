from fastapi import APIRouter

from app.api.v1.endpoints import cars, chat

api_router = APIRouter()
api_router.include_router(cars.router)
api_router.include_router(chat.router)
