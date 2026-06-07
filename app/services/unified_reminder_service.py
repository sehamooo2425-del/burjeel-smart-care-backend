"""
unified_reminder_service.py

Orchestrates sending a reminder notification over both SMS and email simultaneously.
It wraps the individual sms_service and gmail_service calls with retry logic and
runs them concurrently using asyncio tasks so patients receive both channels at once
without one waiting for the other to finish.
"""

import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, Tuple
from app.core.config import settings
from app.services.sms_service import send_textbee_sms
from app.core.gmail_service import send_google_email
from app.schemas.unified_reminder import UnifiedReminderRequest, UnifiedReminderResponse, ServiceStatus

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def retry_operation(operation, *args, max_retries=3, delay=1):
    """
    Execute an operation (sync or async) and automatically retry it on failure,
    using an increasing delay between attempts (exponential back-off).

    Parameters:
        operation: The callable to execute — can be a regular function or a coroutine function.
        *args: Positional arguments to pass to the operation.
        max_retries: How many total attempts to make before giving up (default 3).
        delay: Base delay in seconds; multiplied by attempt number on each retry (default 1s).

    Returns:
        The return value of the operation on success.

    Raises:
        The last exception if all attempts fail.
    """
    last_exception = None
    for attempt in range(max_retries):
        try:
            # asyncio.iscoroutinefunction checks whether the callable needs to be awaited.
            if asyncio.iscoroutinefunction(operation):
                return await operation(*args)
            return operation(*args)
        except Exception as e:
            last_exception = e
            logger.warning(f"Attempt {attempt + 1} failed: {str(e)}")
            if attempt < max_retries - 1:
                # Wait longer after each failure: 1 s, then 2 s, then 3 s...
                await asyncio.sleep(delay * (attempt + 1))
    raise last_exception

async def send_unified_sms(phone_number: str, message: str) -> Tuple[bool, str]:
    """
    Send a single SMS message via the TextBee gateway.

    Parameters:
        phone_number: The recipient's phone number in international format.
        message: The plain-text body of the SMS.

    Returns:
        A tuple of (success: bool, status_message: str).
    """
    success = await send_textbee_sms(phone_number, message)
    if success:
        return True, "SMS sent successfully via TextBee"
    return False, "Failed to send SMS via TextBee"

async def send_unified_email(email: str, subject: str, body: str) -> Tuple[bool, str]:
    """
    Send a single email via the Google Gmail API, with automatic retries on failure.

    Parameters:
        email: The recipient's email address.
        subject: The email subject line.
        body: The HTML or plain-text body of the email.

    Returns:
        A tuple of (success: bool, status_message: str).
    """
    try:
        # send_google_email is a synchronous function (it uses the requests library internally),
        # so we wrap it with retry_operation which can handle both sync and async callables.
        res = await retry_operation(send_google_email, [email], subject, body)
        if res.get("success"):
            return True, res.get("message", "Email sent successfully")
        return False, res.get("message", "Email failed")
    except Exception as e:
        logger.error(f"Email failed after retries: {str(e)}")
        return False, str(e)

async def process_unified_reminder(
    request: UnifiedReminderRequest,
    send_email: bool = True,
    send_sms: bool = True,
) -> UnifiedReminderResponse:
    """
    Dispatch a reminder notification over SMS and/or email based on the caller's flags,
    and return a combined result object describing the outcome of each channel.

    Parameters:
        request:     A UnifiedReminderRequest holding contact details and message bodies.
        send_email:  Whether to send the email channel (default True).
        send_sms:    Whether to send the SMS channel (default True).

    Returns:
        A UnifiedReminderResponse with per-channel status. Skipped channels are marked
        successful so they do not count against overall_success.
    """
    email_body = request.email_content if request.email_content else request.message_content

    skipped = ServiceStatus(success=True, message="Skipped per user preference")

    # Only create tasks for enabled channels that also have valid contact info.
    if send_sms and request.phone_number:
        sms_task = asyncio.create_task(send_unified_sms(request.phone_number, request.message_content))
    else:
        sms_task = None
        if send_sms and not request.phone_number:
            logger.warning("SMS skipped: no phone number available")

    if send_email and request.email_address:
        email_task = asyncio.create_task(send_unified_email(request.email_address, request.subject, email_body))
    else:
        email_task = None
        if send_email and not request.email_address:
            logger.warning("Email skipped: no email address available")

    sms_success,   sms_msg   = (await sms_task)   if sms_task   else (True, "Skipped")
    email_success, email_msg = (await email_task) if email_task else (True, "Skipped")

    return UnifiedReminderResponse(
        sms_status=ServiceStatus(success=sms_success, message=sms_msg),
        email_status=ServiceStatus(success=email_success, message=email_msg),
        overall_success=sms_success and email_success,
    )
