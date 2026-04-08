from fastapi import APIRouter

from app.api.v1.endpoints import cars, chat, feedback, scan

api_router = APIRouter()
api_router.include_router(cars.router)
api_router.include_router(chat.router)
api_router.include_router(feedback.router)
api_router.include_router(scan.router)
