"""
auth_service.py

Handles all user-related business logic for the Burjeel Smart Care system,
including authentication (login), account creation, and profile retrieval/updates.
This file is the bridge between the API layer and the Supabase database for anything
involving users, doctors, and patients.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from app.core.security import verify_password, get_password_hash
from app.schemas import UserCreate, UserUpdate
from app.services.supabase_service import supabase_service
from app.core.supabase import supabase
from fastapi.concurrency import run_in_threadpool

async def authenticate_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    """
    Verify a user's credentials and return their record if login is successful.

    Parameters:
        username: The username submitted from the login form.
        password: The plain-text password submitted from the login form.

    Returns:
        The user's database record as a dict if credentials are valid, or None if login fails.
    """
    user = await supabase_service.get_user_by_username(username)
    if not user:
        return None
    if not verify_password(password, user.get("password_hash")):
        return None

    # Update last login
    # run_in_threadpool is required here because the Supabase Python client is synchronous
    # (blocking), but FastAPI runs in an async event loop. Wrapping the call in
    # run_in_threadpool offloads it to a thread so the event loop is not blocked.
    await run_in_threadpool(
        # A lambda is used to delay the Supabase call so it can be passed as a callable
        # to run_in_threadpool, which will execute it inside the thread.
        lambda: supabase.table("users").update({"last_login": datetime.utcnow().isoformat()}).eq("user_id", user["user_id"]).execute()
    )

    return user

async def create_user(user_in: Any, created_by: Optional[int] = None) -> Dict[str, Any]:
    """
    Create a new user account and, depending on their role, insert a matching
    doctor or patient profile record.

    Parameters:
        user_in: A schema object holding the new user's details (username, email, role, etc.).
        created_by: The user_id of the admin who is creating this account (optional).

    Returns:
        The newly created user record from the database as a dict, or an empty dict on failure.
    """
    hashed_password = get_password_hash(user_in.password)
    user_data = {
        "username": user_in.username,
        "email": user_in.email,
        "password_hash": hashed_password,
        "role": user_in.role,
        "gender": getattr(user_in, "gender", None),
        "created_by": created_by,
        "account_status": "active",
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat()
    }
    created_user = await supabase_service.create_user(user_data)
    
    if not created_user:
        return {}

    user_id = created_user.get("user_id")

    try:
        if user_in.role == "doctor":
            doctor_data = {
                "user_id": user_id,
                "specialty": getattr(user_in, "specialty", None),
                "license_number": getattr(user_in, "license_number", None),
                "department": getattr(user_in, "department", None),
                "created_at": datetime.utcnow().isoformat()
            }
            # Insert a row into the 'doctors' table linked to the new user's ID.
            await run_in_threadpool(lambda: supabase.table("doctors").insert(doctor_data).execute())

        elif user_in.role == "patient" and getattr(user_in, "full_name", None):
            patient_data = {
                "user_id": user_id,
                "full_name": getattr(user_in, "full_name"),
                "phone_number": getattr(user_in, "phone_number", None),
                "medical_record_ref": getattr(user_in, "medical_record_ref", None),
                "registered_date": getattr(user_in, "registered_date", datetime.utcnow().isoformat().split('T')[0])
            }
            # Insert a row into the 'patients' table linked to the new user's ID.
            await run_in_threadpool(lambda: supabase.table("patients").insert(patient_data).execute())
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to create specific record for user {user_id}. Rolling back. Error: {str(e)}")
        # Manual rollback: if the doctor/patient insert fails, delete the user row that was
        # already created so the database is not left in a broken half-created state.
        await run_in_threadpool(lambda: supabase.table("users").delete().eq("user_id", user_id).execute())
        raise ValueError(f"Failed to create {user_in.role} record due to system or database constraint error.")

    return created_user

async def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    """
    Look up a single user by their username.

    Parameters:
        username: The exact username string to search for.

    Returns:
        The user record as a dict, or None if no matching user exists.
    """
    return await supabase_service.get_user_by_username(username)

async def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    """
    Look up a single user by their numeric primary key.

    Parameters:
        user_id: The integer primary key of the user to retrieve.

    Returns:
        The user record as a dict, or None if not found.
    """
    result = await run_in_threadpool(
        lambda: supabase.table("users").select("*").eq("user_id", user_id).execute()
    )
    return result.data[0] if result.data else None

async def get_users_by_role(role: str) -> List[Dict[str, Any]]:
    """
    Retrieve all users that share the given role (e.g. 'doctor', 'patient', 'admin').
    For doctors, the response is enriched with specialty, department, and license details
    fetched via a joined query to the 'doctors' table.

    Parameters:
        role: The role string to filter by (matches the 'role' column in the users table).

    Returns:
        A list of user dicts. Doctor records include flattened doctor-profile fields.
    """
    if role == "doctor":
        # Use Supabase's join syntax with the explicit foreign key name to avoid ambiguity
        # when multiple foreign keys exist between the same two tables.
        result = await run_in_threadpool(
            lambda: supabase.table("users").select("*, doctors!doctors_user_id_fkey(specialty, department, license_number)").eq("role", role).execute()
        )
        data = result.data if result.data else []
        for user in data:
            if "doctors" in user and user["doctors"]:
                # Supabase may return joined rows as a list (one-to-many) or a dict (one-to-one).
                # We normalise to a single dict here.
                doctor_info = user["doctors"][0] if isinstance(user["doctors"], list) else user["doctors"]
                user["specialty"] = doctor_info.get("specialty")
                user["department"] = doctor_info.get("department")
                user["license_number"] = doctor_info.get("license_number")
                # Remove the nested 'doctors' key so callers get a flat structure.
                del user["doctors"]
        return data
    else:
        result = await run_in_threadpool(
            lambda: supabase.table("users").select("*").eq("role", role).execute()
        )
        return result.data if result.data else []

async def get_all_users() -> List[Dict[str, Any]]:
    """
    Retrieve every user record in the system regardless of role.

    Returns:
        A list of all user dicts from the 'users' table.
    """
    result = await run_in_threadpool(
        lambda: supabase.table("users").select("*").execute()
    )
    return result.data if result.data else []

async def update_user(user_id: int, user_in: Dict[str, Any] | UserUpdate) -> Dict[str, Any]:
    """
    Update an existing user's profile, routing role-specific fields to the correct table.
    Fields that belong to 'doctors' or 'patients' are separated and written to those tables,
    while general user fields (email, password_hash, etc.) are written to 'users'.

    Parameters:
        user_id: The numeric ID of the user to update.
        user_in: Either a Pydantic UserUpdate schema or a plain dict containing the fields to change.

    Returns:
        The updated user row from the 'users' table as a dict, or an empty dict if only
        role-specific fields were provided.
    """
    # model_dump(exclude_unset=True) returns only the fields the caller actually provided,
    # skipping fields that were left at their default/None value.
    if hasattr(user_in, "model_dump"):
        update_data = user_in.model_dump(exclude_unset=True)
    else:
        update_data = dict(user_in)

    # Extract doctor/patient specific fields before updating users table
    doctor_fields = ["specialty", "department", "license_number"]
    # pop() removes each key from update_data and collects it into doctor_update so it is
    # not accidentally sent to the 'users' table where those columns don't exist.
    doctor_update = {k: update_data.pop(k) for k in doctor_fields if k in update_data}

    patient_fields = ["full_name", "phone_number", "medical_record_ref", "registered_date"]
    patient_update = {k: update_data.pop(k) for k in patient_fields if k in update_data}

    if update_data:
        update_data["updated_at"] = datetime.utcnow().isoformat()
        result = await run_in_threadpool(
            lambda: supabase.table("users").update(update_data).eq("user_id", user_id).execute()
        )
        updated_user = result.data[0] if result.data else {}
    else:
        # If there are only role specific fields
        updated_user = {}

    if doctor_update:
        await run_in_threadpool(lambda: supabase.table("doctors").update(doctor_update).eq("user_id", user_id).execute())

    # We won't update patients table here since there is a dedicated patient update endpoint or
    # if it's admin update, we can update it too:
    if patient_update:
        # Check if patient exists, if so update it
        try:
            await run_in_threadpool(lambda: supabase.table("patients").update(patient_update).eq("user_id", user_id).execute())
        except Exception:
            pass  # ignore if not a patient

    return updated_user

