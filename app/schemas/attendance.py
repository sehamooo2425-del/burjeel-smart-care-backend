"""
schemas/attendance.py — Pydantic data shapes for patient appointment attendance.

Attendance records track whether a patient showed up for a scheduled
appointment. Each record links an optional reminder to a patient and
stores the appointment outcome (e.g. "present", "absent", "cancelled").
"""

from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel


class AttendanceBase(BaseModel):
    """
    Core attendance fields shared by create and response schemas.

    reminder_id is Optional because attendance can be recorded even if no
    automated reminder was set up for the appointment.
    """
    reminder_id: Optional[int] = None  # The reminder that prompted this appointment, if any.
    patient_id: int                    # Which patient attended (or didn't attend).
    appointment_date: date             # Calendar date of the appointment (no time needed).
    status: str                        # E.g. "present", "absent", "cancelled".


class AttendanceCreate(AttendanceBase):
    """
    Schema for recording a new attendance entry.

    No additional fields are needed beyond AttendanceBase, so 'pass' is used
    to create the subclass without adding anything new.
    """
    pass


class AttendanceUpdate(BaseModel):
    """
    Schema for updating an attendance record (typically to correct a status).

    Only the status can be updated — the patient and date are fixed once created.
    """
    status: Optional[str] = None  # E.g. change "absent" to "present" after a late check-in.


class AttendanceResponse(AttendanceBase):
    """
    Schema for attendance data returned to the API client.

    Adds read-only server-generated fields: the primary key, who marked the
    attendance, and the exact timestamp when it was recorded.
    """
    attendance_id: int  # Database-generated primary key for this attendance record.
    marked_by: int      # user_id of the staff member who recorded the attendance.
    timestamp: datetime # Exact moment the attendance was marked (includes time).
    created_at: datetime
    updated_at: datetime

    class Config:
        # Allows Pydantic to populate this schema from ORM model instances.
        from_attributes = True
