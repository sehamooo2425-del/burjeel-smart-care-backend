"""
schemas/user.py — Pydantic data shapes for user accounts.

Pydantic schemas define the exact structure of data that flows into and out
of the API. FastAPI uses them to automatically validate incoming JSON (request
bodies) and to serialise Python objects back to JSON (responses). Separating
'create', 'update', and 'response' schemas gives you precise control over
which fields are required, optional, or read-only at each stage.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr


class UserBase(BaseModel):
    """
    Fields shared by every user-related schema.

    Putting common fields in a base class and inheriting from it avoids
    repeating the same field definitions in every schema below.
    """
    username: str
    email: Optional[EmailStr] = None  # EmailStr validates the format — must look like a real email.
    role: str                          # E.g. "admin", "doctor", "patient".
    gender: Optional[str] = None       # Optional means this field can be omitted entirely.
    profile_picture_url: Optional[str] = None


class UserCreate(UserBase):
    """
    Schema for creating a new user account (used in the request body).

    Inherits all fields from UserBase and adds the plain-text password,
    which will be hashed before being stored in the database.
    """
    password: str


class AdminUserCreate(UserCreate):
    """
    Extended creation schema used when an admin registers a doctor or patient.

    Adds role-specific fields on top of the standard UserCreate fields.
    All extra fields are optional so the same schema works for any role.
    """
    specialty: Optional[str] = None
    license_number: Optional[str] = None
    department: Optional[str] = None
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    medical_record_ref: Optional[str] = None  # Reference to an external medical record system.
    registered_date: Optional[str] = None


class UserLogin(BaseModel):
    """
    Schema for the login request body.

    Does not inherit UserBase because a login only needs credentials, not
    the full profile. totp_code supports two-factor authentication (TOTP =
    Time-based One-Time Password, e.g. Google Authenticator).
    """
    username: str
    password: str
    totp_code: Optional[str] = None  # Optional — only required when 2FA is enabled.


class UserUpdate(BaseModel):
    """
    Schema for partial user profile updates (PATCH requests).

    Every field is Optional so clients can send only the fields they want to
    change without having to include the entire user object.
    """
    username: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    account_status: Optional[str] = None  # E.g. "active", "suspended".
    gender: Optional[str] = None
    profile_picture_url: Optional[str] = None
    notification_preferences: Optional[dict] = None  # Flexible key-value map for notification settings.


class AdminUserUpdate(UserUpdate):
    """
    Extended update schema for admins who can also change role-specific fields.

    Inherits all optional fields from UserUpdate and adds doctor/patient ones.
    """
    specialty: Optional[str] = None
    department: Optional[str] = None
    license_number: Optional[str] = None
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    medical_record_ref: Optional[str] = None
    registered_date: Optional[str] = None


class UserResponse(UserBase):
    """
    Schema for the data returned to the client after fetching a user.

    Includes server-generated read-only fields (IDs, timestamps) that are
    never sent by the client but are always returned in responses.
    """
    user_id: int
    last_login: Optional[datetime] = None
    account_status: str
    notification_preferences: Optional[dict] = None
    two_factor_enabled: Optional[bool] = False
    created_at: datetime
    updated_at: datetime

    # Doctor/Patient specific optional fields — included here so that a single
    # response schema can represent any user role without needing separate schemas.
    specialty: Optional[str] = None
    department: Optional[str] = None
    license_number: Optional[str] = None
    full_name: Optional[str] = None
    phone_number: Optional[str] = None

    class Config:
        # from_attributes=True allows Pydantic to read data from ORM model
        # instances (objects with attributes) in addition to plain dictionaries.
        from_attributes = True


class Token(BaseModel):
    """
    Schema for the JSON response returned after a successful login.

    Contains the JWT token the client must store and send with future requests,
    plus the full user profile so the frontend doesn't need a separate API call.
    """
    access_token: str   # The JWT string to include in the Authorization header.
    token_type: str     # Always "bearer" — tells the client how to use the token.
    user: UserResponse  # The logged-in user's profile, nested inside the token response.
