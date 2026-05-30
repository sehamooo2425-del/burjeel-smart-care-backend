"""
config.py — Central configuration for the Burjeel Smart Care API.

All environment variables (secrets, URLs, feature flags) are declared here
in one place. Pydantic reads them automatically from the '.env' file so you
never hard-code sensitive values directly in your source code.
"""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    Pydantic-Settings automatically reads each field from the matching
    environment variable name (case-insensitive) or from the '.env' file.
    Fields without a default value are *required* — the app will refuse to
    start if they are missing.
    """

    APP_NAME: str = "Burjeel Smart Care"
    DEBUG: bool = True  # Set to False in production to hide internal error details.

    # Supabase — the hosted PostgreSQL + Auth backend used as the database.
    SUPABASE_URL: str           # The base URL of your Supabase project.
    SUPABASE_SERVICE_KEY: str   # Service-role key — has full DB access; keep secret.
    SUPABASE_ANON_KEY: str      # Public anon key — safe to expose to clients.

    # JWT (JSON Web Token) settings used when issuing login tokens.
    SECRET_KEY: str                          # Secret used to sign tokens; keep this private.
    ALGORITHM: str = "HS256"                 # HMAC-SHA256 — a standard signing algorithm.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30    # Tokens become invalid after this many minutes.

    # TextBee — optional SMS gateway credentials for sending text reminders.
    KEY: Optional[str] = None        # Optional means this can be left unset (defaults to None).
    DEVICE_ID: Optional[str] = None  # The TextBee device that will send the SMS.

    class Config:
        env_file = ".env"   # Tells Pydantic where to look for variable definitions.
        extra = "ignore"    # Silently ignore any extra variables that appear in the .env file.


# A single shared instance imported by the rest of the codebase.
# Other modules do: 'from app.core.config import settings'
settings = Settings()
