"""
Self-service profile endpoints for the Burjeel Smart Care API.

This module lets any authenticated user manage their own account: updating their profile
details, changing their password, and uploading a profile picture. Users can only modify
their own account — they cannot change their role, status, or user_id via these endpoints.

Accessible by: any authenticated user (all roles).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from app.api.deps import get_current_active_user
from app.schemas.user import UserResponse, UserUpdate
from app.services import auth_service
from app.core.validators import validate_password_complexity
from app.core.security import get_password_hash, verify_password

router = APIRouter()

@router.put("/", response_model=UserResponse)
async def update_profile(
    user_in: UserUpdate,
    current_user: dict = Depends(get_current_active_user)
):
    """
    PUT /profile/ — Any authenticated user.
    Updates the current user's own profile (e.g. full name, email, gender).
    Sensitive fields like role, account_status, and user_id are silently ignored
    even if included in the request body, so users cannot elevate their own privileges.
    Returns the updated user record.
    """
    # exclude_unset=True ensures only fields the user actually sent are in the dict.
    update_data = user_in.model_dump(exclude_unset=True)
    # Strip out any privileged fields so a malicious request cannot change them.
    for key in ["role", "account_status", "user_id"]:
        update_data.pop(key, None)

    updated_user = await auth_service.update_user(current_user["user_id"], update_data)
    return updated_user

import logging
logger = logging.getLogger(__name__)

@router.put("/password")
async def update_password(
    password_data: dict,
    current_user: dict = Depends(get_current_active_user)
):
    """
    PUT /profile/password — Any authenticated user.
    Allows the logged-in user to change their own password. They must supply their current
    password for verification before the new password is accepted and hashed.
    The new password must also pass the complexity rules enforced site-wide.
    """
    old_password = password_data.get("old_password")
    new_password = password_data.get("new_password")

    if not old_password or not new_password:
        logger.warning(f"Password update failed for user {current_user['username']}: Missing old or new password.")
        raise HTTPException(status_code=400, detail="Must provide both old_password and new_password.")

    try:
        # Re-fetch the user record so we have access to the stored password hash for verification.
        user_with_hash = await auth_service.get_user_by_username(current_user["username"])
        if not user_with_hash or "password_hash" not in user_with_hash:
            logger.error(f"System Error: User {current_user['username']} not found or missing password hash.")
            raise HTTPException(status_code=500, detail="System Error: Could not verify current user credentials.")

        # verify_password compares the plain-text old_password against the stored bcrypt hash.
        if not verify_password(old_password, user_with_hash["password_hash"]):
            logger.warning(f"Validation Error: Incorrect current password provided for user {current_user['username']}.")
            raise HTTPException(status_code=400, detail="Validation Error: Incorrect current password.")

        # This raises HTTPException(400) directly if the new password is too weak.
        try:
            validate_password_complexity(new_password)
        except HTTPException as e:
            logger.warning(f"Validation Error: Password complexity failed for user {current_user['username']} - {e.detail}")
            raise e

        # Hash the new password before storing — plain-text passwords must never be saved.
        hashed = get_password_hash(new_password)
        await auth_service.update_user(current_user["user_id"], {"password_hash": hashed})
        logger.info(f"User {current_user['username']} successfully updated their password.")

        return {"message": "Password updated successfully."}
    except HTTPException:
        raise  # Re-raise known HTTP errors so FastAPI sends the correct response.
    except Exception as e:
        logger.error(f"System Error during password update for user {current_user['username']}: {str(e)}")
        raise HTTPException(status_code=500, detail="System Error: An unexpected error occurred while updating the password.")

from fastapi import UploadFile, File
import time
import os

@router.post("/avatar", response_model=UserResponse)
async def upload_avatar(
    # File(...) tells FastAPI this is a required multipart file upload field.
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_active_user)
):
    """
    POST /profile/avatar — Any authenticated user.
    Uploads an image file as the user's profile picture. The file is stored in the
    Supabase 'avatars' storage bucket and the resulting public URL is saved on the user
    record. Only image files (MIME type starting with 'image/') are accepted.
    Returns the updated user record including the new profile_picture_url.
    """
    from app.core.supabase import supabase

    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image.")

    try:
        file_bytes = await file.read()
        file_extension = os.path.splitext(file.filename)[1]
        # Include a Unix timestamp in the filename to avoid overwriting previous avatars.
        file_path = f"{current_user['user_id']}_avatar_{int(time.time())}{file_extension}"

        # Upload the raw bytes to the 'avatars' bucket in Supabase Storage.
        result = supabase.storage.from_("avatars").upload(
            file_path,
            file_bytes,
            {"content-type": file.content_type}
        )

        # Retrieve the publicly accessible URL so the frontend can display the image.
        public_url = supabase.storage.from_("avatars").get_public_url(file_path)

        # Persist the URL on the user record so it is returned with every profile fetch.
        updated_user = await auth_service.update_user(current_user["user_id"], {"profile_picture_url": public_url})
        return updated_user
    except Exception as e:
        logger.error(f"Error uploading avatar for user {current_user['user_id']}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to upload avatar: {str(e)}")
