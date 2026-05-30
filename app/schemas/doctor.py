"""
schemas/doctor.py — Pydantic data shapes for doctor profiles.

Doctors are a specialised type of user. These schemas handle the
doctor-specific clinical attributes (specialty, license number, department)
that exist in a separate 'doctors' table alongside the main 'users' table.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class DoctorBase(BaseModel):
    """
    Core doctor fields shared by create and response schemas.

    specialty and license_number are required (no default value) because
    they are essential for identifying a qualified medical professional.
    """
    specialty: str                    # E.g. "Cardiology", "Pediatrics".
    license_number: str               # The doctor's official medical licence identifier.
    department: Optional[str] = None  # Hospital department; Optional because not all roles need it.


class DoctorCreate(DoctorBase):
    """
    Schema for creating a new doctor profile record.

    The corresponding user account is created separately — this schema
    only covers the doctor-specific extension table.
    """
    pass  # All required fields come from DoctorBase; nothing extra needed here.


class DoctorUpdate(BaseModel):
    """
    Schema for partially updating a doctor's professional details.

    Every field is Optional so that only the changed fields need to be sent,
    rather than the complete doctor profile.
    """
    specialty: Optional[str] = None
    license_number: Optional[str] = None
    department: Optional[str] = None


class DoctorResponse(DoctorBase):
    """
    Schema for doctor profile data returned to the API client.

    Includes the database-generated primary key, a reference to the linked
    user account, and record timestamps.
    """
    doctor_id: int  # Primary key in the 'doctors' table.
    user_id: int    # Foreign key linking this doctor profile to the 'users' table.
    created_at: datetime
    updated_at: datetime

    class Config:
        # Allows Pydantic to read from ORM model instances (attribute access),
        # not just from plain Python dictionaries.
        from_attributes = True
