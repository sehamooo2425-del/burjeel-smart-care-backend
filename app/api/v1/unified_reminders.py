"""
Unified reminder dispatch endpoint for the Burjeel Smart Care API.

This module exposes a single endpoint that sends a notification to a patient via both
SMS (Twilio) and email (Gmail) in one request. It is intended for manual ad-hoc
notifications and includes a simple per-user rate limiter to prevent abuse.

Accessible by: admin and doctor roles.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from app.schemas.unified_reminder import UnifiedReminderRequest, UnifiedReminderResponse
from app.services import unified_reminder_service
from app.api.deps import get_current_active_user, RoleChecker
from datetime import datetime, timedelta
from typing import Dict, Tuple

router = APIRouter()

# Simple in-memory rate limiter: maps each user_id to a list of recent request timestamps.
# NOTE: This resets when the server restarts and is not shared across multiple server instances.
rate_limit_store: Dict[int, list] = {}
RATE_LIMIT_WINDOW = 60  # seconds — the rolling window length
MAX_REQUESTS_PER_WINDOW = 5  # maximum allowed calls per user within the window


def check_rate_limit(user_id: int):
    """
    Enforce a per-user rate limit. Raises HTTP 429 if the user has made more than
    MAX_REQUESTS_PER_WINDOW calls within the last RATE_LIMIT_WINDOW seconds.
    """
    now = datetime.utcnow()
    if user_id not in rate_limit_store:
        rate_limit_store[user_id] = []

    # Discard timestamps older than the rolling window before counting.
    rate_limit_store[user_id] = [
        ts for ts in rate_limit_store[user_id]
        if now - ts < timedelta(seconds=RATE_LIMIT_WINDOW)
    ]

    if len(rate_limit_store[user_id]) >= MAX_REQUESTS_PER_WINDOW:
        # HTTP 429 Too Many Requests tells the client to slow down.
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please try again later."
        )

    # Record this request's timestamp so future calls can count it.
    rate_limit_store[user_id].append(now)


@router.post("/", response_model=UnifiedReminderResponse)
async def send_unified_reminder(
    request: UnifiedReminderRequest,
    current_user: dict = Depends(RoleChecker(["admin", "doctor"]))
):
    """
    POST /unified-reminders/ — Admin or Doctor only.
    Sends a custom notification to a patient via both SMS and email simultaneously.
    Subject to per-user rate limiting (max 5 requests per 60 seconds).
    Returns a response indicating the success or failure of each delivery channel.
    """
    # Block the request early if the user has exceeded their allowed call rate.
    check_rate_limit(current_user["user_id"])

    try:
        response = await unified_reminder_service.process_unified_reminder(request)
        return response
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while processing the reminder: {str(e)}"
        )
