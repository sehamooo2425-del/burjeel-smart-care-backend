"""
schemas/patient.py — Pydantic data shapes for patient records.

Patients are a specialised type of user. These schemas define the data
structures for creating, updating, and returning patient-specific information
(clinic details, medical record references) that extends the base user account.
"""

from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel


class PatientBase(BaseModel):
    """
    Core patient fields shared by create and response schemas.

    'date' (without time) is used for registered_date because the exact hour
    of registration is not clinically relevant — only the calendar date matters.
    """
    full_name: str
    phone_number: str
    medical_record_ref: Optional[str] = None  # External reference ID in a hospital records system.
    registered_date: date                      # Uses Python's date type — just YYYY-MM-DD, no time.


class PatientCreate(PatientBase):
    """
    Schema used when registering a brand-new patient.

    Includes login credentials (username, email, password) in addition to the
    clinical fields from PatientBase because creating a patient also creates
    their user account at the same time.
    """
    username: str
    email: str
    password: str  # Plain-text — will be hashed by the service layer before storage.


class PatientUpdate(BaseModel):
    """
    Schema for partial updates to an existing patient's clinical profile.

    All fields are Optional so a caller can update just one field at a time
    without sending the full patient object.
    """
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    medical_record_ref: Optional[str] = None
    registered_date: Optional[date] = None


class PatientResponse(PatientBase):
    """
    Schema for the patient data returned to API clients.

    Includes database-generated IDs and timestamps that are read-only from
    the client's perspective. Also surfaces user-account fields (username,
    email) because the frontend typically needs them alongside patient details.
    """
    patient_id: int  # The patient table's own primary key.
    user_id: int     # Foreign key linking this patient to the users table.
    username: Optional[str] = None
    email: Optional[str] = None
    gender: Optional[str] = None
    profile_picture_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        # Allows Pydantic to populate this schema from ORM objects (attribute access)
        # in addition to plain dictionaries.
        from_attributes = True
