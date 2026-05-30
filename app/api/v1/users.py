"""
Admin-only user management endpoints for the Burjeel Smart Care API.

This module gives admins elevated control over any user account: changing account status
(active/suspended/inactive), editing profile fields, deleting accounts, and force-resetting
passwords. All endpoints in this file are restricted to the 'admin' role.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from app.api.deps import get_current_active_user, RoleChecker
from app.schemas.user import UserResponse, UserUpdate
from app.services import auth_service
from app.core.security import get_password_hash
from app.core.validators import validate_password_complexity
from typing import List, Optional
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

@router.put("/{user_id}/status", response_model=UserResponse)
async def update_user_status(
    user_id: int,
    status_update: dict,
    current_user: dict = Depends(RoleChecker(["admin"]))
):
    """
    PUT /users/{user_id}/status — Admin only.
    Changes a user's account_status to 'active', 'suspended', or 'inactive'.
    Suspended/inactive users cannot log in even with valid credentials.
    Returns the updated user record.
    """
    new_status = status_update.get("account_status")
    if new_status not in ["active", "suspended", "inactive"]:
        raise HTTPException(status_code=400, detail="Invalid status")

    updated_user = await auth_service.update_user(user_id, {"account_status": new_status})
    return updated_user

from app.schemas.user import UserResponse, UserUpdate, AdminUserUpdate


@router.put("/{user_id}", response_model=UserResponse)
async def admin_update_user(
    user_id: int,
    user_in: AdminUserUpdate,
    current_user: dict = Depends(RoleChecker(["admin"]))
):
    """
    PUT /users/{user_id} — Admin only.
    Allows an admin to edit any field on any user's profile (including role and status).
    Only fields included in the request body are changed. Returns the updated user record.
    """
    # exclude_unset=True means only fields the admin actually provided are applied.
    update_data = user_in.model_dump(exclude_unset=True)
    try:
        updated_user = await auth_service.update_user(user_id, update_data)
        return updated_user
    except Exception as e:
        logger.error(f"System Error: Admin {current_user['user_id']} failed to update user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="System Error: Failed to update user profile.")

@router.delete("/{user_id}")
async def admin_delete_user(
    user_id: int,
    current_user: dict = Depends(RoleChecker(["admin"]))
):
    """
    DELETE /users/{user_id} — Admin only.
    Permanently removes the user account. Related rows (patient profile, etc.) are removed
    automatically if cascade delete is configured in the database schema.
    """
    try:
        from app.core.supabase import supabase
        from fastapi.concurrency import run_in_threadpool
        # Deleting from the users table; cascade rules in the DB handle linked rows.
        await run_in_threadpool(lambda: supabase.table("users").delete().eq("user_id", user_id).execute())

        logger.info(f"Admin {current_user['user_id']} successfully deleted user {user_id}.")
        return {"message": "User deleted successfully."}
    except Exception as e:
        logger.error(f"System Error: Admin {current_user['user_id']} failed to delete user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="System Error: Failed to delete user.")

@router.post("/{user_id}/reset-password")
async def admin_reset_password(
    user_id: int,
    password_data: dict,
    current_user: dict = Depends(RoleChecker(["admin"]))
):
    """
    POST /users/{user_id}/reset-password — Admin only.
    Allows an admin to set a new password for any user without knowing the old one.
    The new password is validated for complexity before being hashed and saved.
    """
    new_password = password_data.get("new_password")

    if not new_password:
        logger.warning(f"Validation Error: Admin {current_user['user_id']} attempted to reset password for user {user_id} without providing new_password.")
        raise HTTPException(status_code=400, detail="Validation Error: new_password must be provided.")

    try:
        # Ensure the new password meets security requirements (length, special chars, etc.).
        validate_password_complexity(new_password)
    except HTTPException as e:
        logger.warning(f"Validation Error: Admin {current_user['user_id']} password reset for user {user_id} failed complexity check: {e.detail}")
        raise e

    try:
        # Hash the plain-text password before storing — never save passwords in plain text.
        hashed = get_password_hash(new_password)
        await auth_service.update_user(user_id, {"password_hash": hashed})

        logger.info(f"Admin {current_user['user_id']} successfully reset password for user {user_id}.")
        return {"message": "Password reset successfully."}
    except Exception as e:
        logger.error(f"System Error: Admin {current_user['user_id']} failed to reset password for user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="System Error: An unexpected error occurred while resetting the password.")

