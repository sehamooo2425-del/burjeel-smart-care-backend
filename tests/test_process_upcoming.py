import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.api.deps import get_current_active_user
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

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

@patch("app.services.reminder_service.supabase")
@patch("app.services.reminder_service.process_unified_reminder")
def test_process_upcoming_reminders(mock_process, mock_supabase):
    # Setup mock data for reminders
    mock_supabase.table().select().gte().lte().eq().execute.return_value = MagicMock(
        data=[
            {
                "reminder_id": 101,
                "patient_id": 1,
                "medication_name": "Aspirin",
                "scheduled_date": (datetime.utcnow() + timedelta(days=1)).date().isoformat(),
                "reminder_type": "medication",
                "sent_status": "pending",
                "patients": {
                    "phone_number": "+1234567890",
                    "users!patients_user_id_fkey": {
                        "email": "patient@example.com"
                    }
                }
            }
        ]
    )
    
    # Mock the unified reminder response
    mock_process.return_value = MagicMock(overall_success=True)
    
    # Mock the update call
    mock_supabase.table().update().eq().execute.return_value = MagicMock(data=[{}])
    
    response = client.get("/api/v1/reminders/process-upcoming")
    
    assert response.status_code == 200
    data = response.json()
    assert data["total_found"] == 1
    assert data["processed"] == 1
    assert data["successful"] == 1
    
    # Verify that process_unified_reminder was called
    assert mock_process.called
