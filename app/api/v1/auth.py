"""
Authentication endpoints for the Burjeel Smart Care API.

This module handles user registration, login, and two-factor authentication (2FA).
It also provides admin-only user creation and listing.

Accessible by:
- Public (no login required): /register, /login
- Any logged-in user: /me, /users, /2fa/setup, /2fa/verify
- Admin only: /create-user
"""

from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status, Request
from app.core.security import create_access_token
from app.core.config import settings
from app.core.validators import validate_password_complexity
from app.schemas import UserCreate, AdminUserCreate, UserLogin, UserResponse, Token
from app.services import auth_service
from app.api.deps import get_current_active_user, RoleChecker
from typing import List, Optional
import pyotp
import asyncio
from fastapi.concurrency import run_in_threadpool
from app.core.gmail_service import send_google_email
from app.services.reminder_service import get_template

async def send_registration_email(user_in, user_dict):
    """Send a welcome email to a newly registered user. Silently logs and ignores any errors so a failed email never blocks registration."""
    email = getattr(user_in, "email", None)
    if not email:
        return
    try:
        email_html = get_template(
            "user_registered",
            ext="html",
            user_name=getattr(user_in, "full_name", user_in.username),
            username=user_in.username,
            password=user_in.password
        )
        await run_in_threadpool(send_google_email, [email], "You are registered to Burjeel Smart Care", email_html)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to send registration email: {str(e)}")

# Note: We must import the limiter from main. However, to avoid circular imports, 
# you can use `request.app.state.limiter` directly in the endpoint, 
# or import a global limiter. For now, we'll try to import `limiter` from `app.main`
# BUT since the router is mounted in main, importing from main might cause circular import.
# We will use dependency injection for Request.

router = APIRouter()


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_in: UserCreate
):
    """
    POST /register — Public endpoint.
    Allows a new patient to self-register. Only the 'patient' role is permitted here;
    staff accounts must be created by an admin via /create-user.
    Returns the newly created user object on success.
    """
    # Only allow registration for patients
    if user_in.role != "patient":
        # HTTPException stops the request and returns an error response to the caller.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is only allowed for patients"
        )

    # Ensure the password meets security rules (length, symbols, etc.) before saving.
    validate_password_complexity(user_in.password)

    existing_user = await auth_service.get_user_by_username(user_in.username)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )
    user = await auth_service.create_user(user_in)
    # Fire the welcome email in the background so the API response isn't delayed.
    asyncio.create_task(send_registration_email(user_in, user))
    return user


@router.post("/login", response_model=Token)
async def login(
    request: Request,
    user_in: UserLogin
):
    """
    POST /login — Public endpoint.
    Authenticates a user with username and password. If the account has 2FA enabled,
    a valid TOTP code must also be supplied. Returns a JWT access token on success.
    """
    user = await auth_service.authenticate_user(user_in.username, user_in.password)
    if not user:
        # 401 Unauthorized means the credentials were wrong.
        # The WWW-Authenticate header tells the client that Bearer token auth is expected.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user.get("two_factor_enabled"):
        # If the user has 2FA turned on, they must also send a time-based one-time password.
        if not user_in.totp_code:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="2FA is enabled. Please provide a totp_code."
            )
        # pyotp.TOTP verifies the 6-digit code against the stored secret.
        totp = pyotp.TOTP(user["two_factor_secret"])
        if not totp.verify(user_in.totp_code):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid 2FA code."
            )

    if user.get("account_status") != "active":
        # Prevent suspended or inactive accounts from logging in even with correct credentials.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive or suspended"
        )

    # Build a JWT that expires after the configured number of minutes.
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["username"]}, expires_delta=access_token_expires
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user
    }


@router.post("/create-user", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user_admin(
    user_in: AdminUserCreate,
    # Depends(RoleChecker(["admin"])) injects role enforcement: only admins can reach this code.
    current_user: dict = Depends(RoleChecker(["admin"]))
):
    """
    POST /create-user — Admin only.
    Allows an admin to create any type of user account (doctor, etc.).
    Sends a welcome email to the new user and records who created the account.
    Returns the newly created user object.
    """
    validate_password_complexity(user_in.password)
    existing_user = await auth_service.get_user_by_username(user_in.username)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )
    try:
        # Pass current_user's ID so the new account is linked to its creator.
        user = await auth_service.create_user(user_in, created_by=current_user["user_id"])
        asyncio.create_task(send_registration_email(user_in, user))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return user

@router.get("/users", response_model=List[UserResponse])
async def get_users_list(
    role: Optional[str] = None,
    # get_current_active_user ensures any logged-in, active user can call this endpoint.
    current_user: dict = Depends(get_current_active_user)
):
    """
    GET /users — Any authenticated user.
    Returns a list of all users. Pass ?role=doctor (or another role) to filter the results.
    """
    if role:
        users = await auth_service.get_users_by_role(role)
    else:
        users = await auth_service.get_all_users()
    return users

@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: dict = Depends(get_current_active_user)
):
    """
    GET /me — Any authenticated user.
    Returns the profile of the currently logged-in user based on their JWT token.
    """
    return current_user

@router.post("/2fa/setup")
async def setup_2fa(current_user: dict = Depends(get_current_active_user)):
    """
    POST /2fa/setup — Any authenticated user.
    Generates a new 2FA secret and returns a provisioning URI that authenticator apps
    (e.g. Google Authenticator) can scan as a QR code. Call /2fa/verify next to activate.
    """
    if current_user.get("two_factor_enabled"):
        raise HTTPException(status_code=400, detail="2FA is already enabled.")

    # Generate a random base-32 secret key that will be shared with the authenticator app.
    secret = pyotp.random_base32()
    await auth_service.update_user(current_user["user_id"], {"two_factor_secret": secret})

    totp = pyotp.TOTP(secret)
    # The provisioning URI encodes the secret in a format readable by authenticator apps.
    provisioning_uri = totp.provisioning_uri(name=current_user["email"], issuer_name="Burjeel Smart Care")
    return {"secret": secret, "uri": provisioning_uri}

@router.post("/2fa/verify")
async def verify_2fa(code: str, current_user: dict = Depends(get_current_active_user)):
    """
    POST /2fa/verify — Any authenticated user.
    Confirms the TOTP code from the authenticator app and permanently enables 2FA on
    the account. Must be called after /2fa/setup.
    """
    if current_user.get("two_factor_enabled"):
        raise HTTPException(status_code=400, detail="2FA is already enabled.")

    secret = current_user.get("two_factor_secret")
    if not secret:
        raise HTTPException(status_code=400, detail="Please call /2fa/setup first.")

    totp = pyotp.TOTP(secret)
    if not totp.verify(code):
        raise HTTPException(status_code=400, detail="Invalid code.")

    # Flip the flag so future logins require a TOTP code.
    await auth_service.update_user(current_user["user_id"], {"two_factor_enabled": True})
    return {"message": "2FA successfully enabled."}
