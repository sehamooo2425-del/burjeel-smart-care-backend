"""
security.py — Password hashing and JWT token utilities.

This module handles two important security concerns:
  1. Passwords are never stored in plain text — bcrypt converts them into an
     irreversible hash before saving to the database.
  2. After a successful login, a signed JWT (JSON Web Token) is issued.
     The token proves who the user is on every subsequent request without
     needing to query the database each time.
"""

import bcrypt
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from .config import settings


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Check whether a plain-text password matches a stored bcrypt hash.

    Args:
        plain_password:  The raw password the user just typed in.
        hashed_password: The bcrypt hash that was saved to the database at
                         registration time.

    Returns:
        True if the password is correct, False otherwise (including on any error).
    """
    try:
        # bcrypt requires bytes, so we encode both strings to UTF-8 before comparing.
        # checkpw re-hashes the plain password with the salt embedded in the stored
        # hash and then compares — it never decrypts the original.
        return bcrypt.checkpw(
            plain_password.encode('utf-8'),
            hashed_password.encode('utf-8')
        )
    except Exception:
        # Return False on any unexpected error so we never accidentally grant access.
        return False


def get_password_hash(password: str) -> str:
    """
    Hash a plain-text password using bcrypt so it can be stored safely.

    Args:
        password: The raw password chosen by the user.

    Returns:
        A bcrypt hash string (starts with '$2b$') that is safe to store in the DB.
    """
    # bcrypt has a 72-character limit for the password itself.
    # If the password is longer, we should ideally hash it first (e.g. with SHA256)
    # but for now, let's just use bcrypt directly as it's standard.
    # The error "password cannot be longer than 72 bytes" in passlib
    # is often due to how it handles the salt/config string.

    # gensalt() generates a random 'salt' — extra random data mixed into the hash
    # so that two users with the same password get different stored hashes.
    return bcrypt.hashpw(
        password.encode('utf-8'),
        bcrypt.gensalt()
    ).decode('utf-8')  # Convert the resulting bytes back to a regular string for storage.


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a signed JWT access token containing the given data payload.

    Args:
        data:          A dictionary of claims to embed in the token (e.g. {'sub': username}).
        expires_delta: How long until the token expires. Defaults to the value in settings.

    Returns:
        A compact JWT string that the client sends in the Authorization header.
    """
    # Copy the data so we don't accidentally mutate the caller's original dict.
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        # Fall back to the default expiry defined in config (typically 30 minutes).
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    # 'exp' is a standard JWT claim that tells the receiver when this token expires.
    to_encode.update({"exp": expire})

    # jwt.encode signs the payload with our SECRET_KEY using the chosen ALGORITHM,
    # producing a tamper-proof string of the form: header.payload.signature
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> Optional[dict]:
    """
    Verify and decode a JWT access token, returning its payload if valid.

    Args:
        token: The JWT string received from the client (without the 'Bearer ' prefix).

    Returns:
        The decoded payload dictionary on success, or None if the token is
        invalid, expired, or has been tampered with.
    """
    try:
        # jwt.decode both verifies the signature AND checks the expiry time automatically.
        # algorithms is a list because the spec allows multiple acceptable algorithms.
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        # Any problem (wrong secret, expired, malformed) results in None, not an exception.
        return None
