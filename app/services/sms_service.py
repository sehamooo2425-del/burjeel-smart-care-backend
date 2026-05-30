"""
sms_service.py

Handles outbound SMS delivery for the Burjeel Smart Care system using the TextBee gateway.
TextBee routes SMS messages through a registered Android device identified by a DEVICE_ID.
Both DEVICE_ID and the API KEY must be present in the application settings for sending to work.
"""

import logging
import httpx
from app.core.config import settings

logger = logging.getLogger(__name__)

async def send_textbee_sms(phone_number: str, message: str) -> bool:
    """
    Send a single SMS message to a phone number via the TextBee REST API.
    TextBee works by routing messages through an Android phone registered to your account,
    so it requires both an API key and the unique device ID of that phone.

    Parameters:
        phone_number: The recipient's phone number, including country code (e.g. '+96812345678').
        message: The plain-text content of the SMS.

    Returns:
        True if TextBee accepted the message (HTTP 200 or 201), False otherwise.
    """
    if not settings.KEY:
        logger.error("TextBee KEY not configured")
        return False

    # TextBee API requires device ID in the URL.
    # The current KEY in settings might be the API key,
    # but we also need a DEVICE_ID if we are to use the correct endpoint.
    # Based on TextBee documentation, the endpoint is:
    # https://api.textbee.dev/api/v1/gateway/devices/{DEVICE_ID}/send-sms

    # As I don't have a DEVICE_ID environment variable, I'll log an error for now
    # or you might need to add DEVICE_ID to settings.

    # Assuming you might have the Device ID or it's part of your configuration.
    device_id = settings.DEVICE_ID
    if not device_id:
        logger.error("TextBee DEVICE_ID not configured")
        return False

    url = f"https://api.textbee.dev/api/v1/gateway/devices/{device_id}/send-sms"
    # TextBee expects a list of recipients so multiple numbers could be sent at once,
    # but we always pass a single number here.
    payload = {
        "recipients": [phone_number],
        "message": message
    }
    headers = {
        "x-api-key": settings.KEY,
        "Content-Type": "application/json"
    }

    try:
        # httpx.AsyncClient is the async equivalent of the popular requests library.
        # Using it as a context manager (with) ensures the HTTP connection is properly
        # closed after the request completes.
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers, timeout=10)
            if response.status_code in [200, 201]:
                logger.info(f"SMS sent successfully via TextBee to {phone_number}")
                return True
            else:
                logger.error(f"TextBee API error: {response.text}")
                return False
    except Exception as e:
        logger.error(f"Failed to send SMS via TextBee: {str(e)}")
        return False
