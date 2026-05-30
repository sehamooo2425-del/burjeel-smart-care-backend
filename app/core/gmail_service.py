"""
gmail_service.py — Sends emails through a Google Apps Script web app.

Instead of connecting to Gmail's SMTP server directly, this module calls a
Google Apps Script URL that acts as a relay. This approach avoids the need
for OAuth credentials in the backend — authentication is handled by a token
shared between the script and this service.
"""

import requests
import os
from dotenv import load_dotenv

load_dotenv()


def send_google_email(recipient_emails, subject, html_body):
    """
    Send an HTML email to one or more recipients via Google Apps Script.

    Args:
        recipient_emails: A single email address string OR a list of addresses.
        subject:          The email subject line.
        html_body:        The email body as an HTML string (supports tags like <b>, <br> etc.).

    Returns:
        A dict with 'success' (bool) and 'message' (str) describing the outcome.
        On success it also includes 'recipients' with the comma-joined address list.
    """

    # 1. Load Variables
    # These secrets live in .env so they are not hard-coded in source control.
    GOOGLE_SCRIPT_URL = os.environ.get("GOOGLE_SCRIPT_URL")
    EMAIL_TOKEN = os.environ.get("EMAIL_TOKEN")   # Shared secret that authenticates us to the script.
    sender_name = os.environ.get("EMAIL_NAME")

    # 2. Handle Recipients
    # The Google Script expects a comma-separated string, so convert a list if needed.
    if isinstance(recipient_emails, list):
        recipient_emails = ",".join(recipient_emails)

    # 3. Build Payload
    # This dictionary will be JSON-encoded and sent as the POST body.
    payload = {
        "token": EMAIL_TOKEN,
        "to": recipient_emails,
        "subject": subject,
        "body": html_body,     # This is your HTML content.
        "name": sender_name,   # This is your "From" display name.
        "attachments": []      # No file attachments for now; the list is kept for future use.
    }

    # 4. Send Request
    try:
        # timeout=20 means we give up waiting after 20 seconds to avoid hanging the API.
        response = requests.post(GOOGLE_SCRIPT_URL, json=payload, timeout=20)

        # 5. Process Response
        # The Google Apps Script returns a plain-text response containing "Success" on success.
        if "Success" in response.text:
            return {
                'success': True,
                'message': f'Email sent successfully to {len(recipient_emails.split(","))} recipient(s)',
                'recipients': recipient_emails,
            }
        else:
            return {"success": False, "message": f"Script Error: {response.text}"}

    except Exception as e:
        # Catch network errors (timeouts, DNS failures, etc.) and return them as a failure dict
        # rather than crashing the caller with an unhandled exception.
        return {"success": False, "message": str(e)}