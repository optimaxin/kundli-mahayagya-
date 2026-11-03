from fastapi import APIRouter

from app.api.v1 import admin, auth, bookings, health, offline, qr, registrations, reports, scanner, sessions

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(registrations.router)
api_router.include_router(bookings.router)
api_router.include_router(bookings.family_router)
api_router.include_router(sessions.router)
api_router.include_router(sessions.kund_router)
api_router.include_router(qr.router)
api_router.include_router(scanner.router)
api_router.include_router(scanner.checkins_router)
api_router.include_router(admin.router)
api_router.include_router(reports.router)
api_router.include_router(offline.router)
