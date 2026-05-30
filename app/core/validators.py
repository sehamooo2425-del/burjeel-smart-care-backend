"""
validators.py — Reusable input validation helpers for the API.

This module contains functions that enforce business rules on incoming data
before it reaches the database. Keeping validators here (rather than
scattering them across route handlers) makes the rules easy to find and reuse.
"""

import re
from fastapi import HTTPException, status


def validate_password_complexity(password: str) -> None:
    """
    Enforce minimum password-strength rules, raising an HTTP 400 error on failure.

    This function is called during user registration (and password changes) to
    ensure users choose passwords that are harder to guess or brute-force.

    Args:
        password: The plain-text password string submitted by the user.

    Returns:
        None — the function only raises on failure; a silent return means success.

    Raises:
        HTTPException (400 Bad Request): if the password violates any rule below.
    """

    if len(password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters long."
        )

    # re.search scans the entire string for at least one character matching the pattern.
    # r"[A-Z]" means: any single uppercase ASCII letter.
    if not re.search(r"[A-Z]", password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must contain at least one uppercase letter."
        )

    # r"[a-z]" means: any single lowercase ASCII letter.
    if not re.search(r"[a-z]", password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must contain at least one lowercase letter."
        )

    # r"[0-9]" means: any single digit.
    if not re.search(r"[0-9]", password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must contain at least one number."
        )

    # r"[@$!%*?&#]" is a character class listing the only accepted special characters.
    if not re.search(r"[@$!%*?&#]", password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must contain at least one special character (@$!%*?&#)."
        )
