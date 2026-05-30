"""
main.py — Application entry point for the Burjeel Smart Care API.

This is the first file FastAPI reads when the server starts. It creates the
main 'app' object, registers middleware (like CORS and rate-limiting), and
wires up all the feature routers so their endpoints become reachable.
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from app.core.config import settings
from app.api.v1 import auth, patients, reminders, attendance, reports, chat, unified_reminders, users, profile

# Create a rate-limiter that identifies each caller by their IP address.
# This prevents a single client from flooding the API with too many requests.
limiter = Limiter(key_func=get_remote_address)

# The central FastAPI application instance — everything is registered on this object.
app = FastAPI(
    title=settings.APP_NAME,
    debug=settings.DEBUG
)

# Attach the limiter to the app so route handlers can access it via 'app.state'.
app.state.limiter = limiter
# Tell FastAPI to use slowapi's built-in handler when a rate limit is exceeded.
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS (Cross-Origin Resource Sharing) middleware allows the browser-based
# frontend (running on a different domain/port) to talk to this API.
# allow_origins=["*"] permits requests from any origin — fine for development,
# but should be locked down to specific domains in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Each router groups related endpoints together (e.g. all /auth/* routes).
# The 'prefix' prepends a path to every route in that router, and 'tags'
# control how they appear in the auto-generated /docs interface.
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(patients.router, prefix="/api/v1/patients", tags=["Patients"])
app.include_router(reminders.router, prefix="/api/v1/reminders", tags=["Reminders"])
app.include_router(attendance.router, prefix="/api/v1/attendance", tags=["Attendance"])
app.include_router(reports.router, prefix="/api/v1/reports", tags=["Reports"])
app.include_router(chat.router, prefix="/api/v1/chat", tags=["Chat"])
app.include_router(unified_reminders.router, prefix="/api/v1/unified-reminders", tags=["Unified Reminders"])
app.include_router(users.router, prefix="/api/v1/users", tags=["Users"])
app.include_router(profile.router, prefix="/api/v1/profile", tags=["Profile"])


@app.get("/")
async def root():
    """
    Root endpoint — a simple welcome message.

    Returns a JSON object confirming the API is running and showing its version.
    Useful for quickly checking that the server started correctly.
    """
    return {"message": "Burjeel Smart Care Backend API", "version": "1.0.0"}


@app.get("/health")
async def health_check():
    """
    Health-check endpoint used by deployment platforms (e.g. Docker, cloud services).

    Returns a JSON object with status "healthy" so load balancers know the
    server is alive and ready to accept traffic.
    """
    return {"status": "healthy"}
