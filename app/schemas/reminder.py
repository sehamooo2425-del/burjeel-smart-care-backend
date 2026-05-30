"""
schemas/reminder.py — Pydantic data shapes for patient reminders.

Reminders are scheduled notifications sent to patients (e.g. "take your
medication" or "you have a doctor appointment"). These schemas define what
data is required to create or update a reminder and what is returned to
the API client.
"""

from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel


class ReminderBase(BaseModel):
    """
    Core reminder fields shared across create and response schemas.

    'datetime' (not just 'date') is used for scheduled_date because reminders
    need both a date and a time to be sent at the right moment.
    """
    patient_id: int                         # Which patient this reminder belongs to.
    display_name: Optional[str] = None      # A human-readable label, e.g. "Morning Insulin".
    scheduled_date: datetime                # The exact date and time to send the reminder.
    reminder_type: str = "medication"       # Default value — can be "medication" or "doctor_visit".


class ReminderCreate(ReminderBase):
    """
    Schema for creating a new reminder.

    Uses 'pass' because no extra fields are needed beyond ReminderBase —
    inheritance gives us everything we need.
    """
    pass


class ReminderUpdate(BaseModel):
    """
    Schema for partially updating an existing reminder.

    Includes success_sent and failed_sent so the system can record how many
    notification delivery attempts succeeded or failed after sending.
    All fields are Optional to allow targeted, single-field updates.
    """
    display_name: Optional[str] = None
    scheduled_date: Optional[datetime] = None
    reminder_type: Optional[str] = None
    success_sent: Optional[int] = None  # Count of successfully delivered notifications.
    failed_sent: Optional[int] = None   # Count of failed delivery attempts.


class ReminderResponse(ReminderBase):
    """
    Schema for reminder data returned to the API client.

    Includes the database-generated primary key, delivery counters, and
    timestamps that the client needs to display reminder history.
    """
    reminder_id: int
    success_sent: int = 0  # Default to 0 — no notifications sent yet when first created.
    failed_sent: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        # Allows Pydantic to read data from ORM model instances as well as dicts.
        from_attributes = True
