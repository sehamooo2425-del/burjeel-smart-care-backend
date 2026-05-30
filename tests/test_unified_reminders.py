import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.api.deps import get_current_active_user
from unittest.mock import patch, MagicMock

client = TestClient(app)

# Mock user for authentication
mock_user = {
    "user_id": 1,
    "username": "testadmin",
    "role": "admin",
    "account_status": "active"
}

def override_get_current_active_user():
    return mock_user

app.dependency_overrides[get_current_active_user] = override_get_current_active_user

@patch("app.services.unified_reminder_service.send_unified_sms")
@patch("app.services.unified_reminder_service.send_unified_email")
def test_send_unified_reminder_success(mock_email, mock_sms):
    # Setup mocks
    mock_sms.return_value = (True, "SMS sent successfully")
    mock_email.return_value = (True, "Email sent successfully")
    
    payload = {
        "phone_number": "+1234567890",
        "email_address": "test@example.com",
        "message_content": "Test reminder message"
    }
    
    response = client.post("/api/v1/unified-reminders/", json=payload)
    
    assert response.status_code == 200
    data = response.json()
    assert data["overall_success"] is True
    assert data["sms_status"]["success"] is True
    assert data["email_status"]["success"] is True

@patch("app.services.unified_reminder_service.send_unified_sms")
@patch("app.services.unified_reminder_service.send_unified_email")
def test_send_unified_reminder_partial_failure(mock_email, mock_sms):
    # Setup mocks: SMS fails, Email succeeds
    mock_sms.return_value = (False, "Twilio error")
    mock_email.return_value = (True, "Email sent successfully")
    
    payload = {
        "phone_number": "+1234567890",
        "email_address": "test@example.com",
        "message_content": "Test reminder message"
    }
    
    response = client.post("/api/v1/unified-reminders/", json=payload)
    
    assert response.status_code == 200
    data = response.json()
    assert data["overall_success"] is False
    assert data["sms_status"]["success"] is False
    assert data["email_status"]["success"] is True

def test_send_unified_reminder_invalid_input():
    # Invalid email and phone
    payload = {
        "phone_number": "invalid",
        "email_address": "not-an-email",
        "message_content": ""
    }
    
    response = client.post("/api/v1/unified-reminders/", json=payload)
    assert response.status_code == 422  # Validation error
