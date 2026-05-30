"""
Patient management endpoints for the Burjeel Smart Care API.

This module provides CRUD (Create, Read, Update, Delete) operations for patient records.
Creating, updating, and deleting patients requires an admin or doctor role.
Patients can view their own profile via the /me endpoint.
"""

from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from app.schemas import PatientCreate, PatientUpdate, PatientResponse, UserCreate
from app.services import auth_service
from app.services.supabase_service import supabase_service
from app.api.deps import get_current_active_user, RoleChecker
from datetime import datetime

router = APIRouter()


@router.post("/", response_model=PatientResponse, status_code=status.HTTP_201_CREATED)
async def create_patient(
    patient_in: PatientCreate,
    # Only admins and doctors are allowed to register new patients.
    current_user: dict = Depends(RoleChecker(["admin", "doctor"]))
):
    """
    POST /patients/ — Admin or Doctor only.
    Creates both a login account (in the users table) and a patient profile record.
    Returns the newly created patient profile on success.
    """
    existing_user = await auth_service.get_user_by_username(patient_in.username)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )

    # Build a standard UserCreate object so we can reuse the auth service to make the login account.
    user_in = UserCreate(
        username=patient_in.username,
        email=patient_in.email,
        password=patient_in.password,
        role="patient"
    )
    user = await auth_service.create_user(user_in, created_by=current_user["user_id"])

    # Separately build the patient-specific fields to insert into the patients table.
    patient_data = {
        "user_id": user["user_id"],
        "full_name": patient_in.full_name,
        "phone_number": patient_in.phone_number,
        "medical_record_ref": patient_in.medical_record_ref,
        # Convert the date object to an ISO string so Supabase accepts it.
        "registered_date": patient_in.registered_date.isoformat(),
        "created_by": current_user["user_id"],
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat()
    }

    return await supabase_service.create_patient(patient_data)


@router.get("/me", response_model=PatientResponse)
async def get_current_patient(
    # Only users with the 'patient' role can reach this endpoint.
    current_user: dict = Depends(RoleChecker(["patient"]))
):
    """
    GET /patients/me — Patient only.
    Returns the full patient profile of the currently logged-in patient, including
    account details (username, email, gender) joined from the users table.
    """
    from app.core.supabase import supabase
    from fastapi.concurrency import run_in_threadpool

    # The "!" syntax tells Supabase which foreign key relationship to use when joining tables,
    # preventing ambiguity when multiple FK relationships exist between patients and users.
    result = await run_in_threadpool(
        lambda: supabase.table("patients").select("*, users!patients_user_id_fkey(username, email, gender, profile_picture_url)").eq("user_id", current_user["user_id"]).execute()
    )

    data = result.data if result.data else []
    if not data:
        raise HTTPException(status_code=404, detail="Patient profile not found")

    patient = data[0]
    if "users" in patient and patient["users"]:
        # Supabase may return the joined row as a list or a dict depending on the relationship type.
        user_info = patient["users"][0] if isinstance(patient["users"], list) else patient["users"]
        patient["username"] = user_info.get("username")
        patient["email"] = user_info.get("email")
        patient["gender"] = user_info.get("gender")
        patient["profile_picture_url"] = user_info.get("profile_picture_url")
        # Remove the nested 'users' dict so the response matches the flat PatientResponse schema.
        del patient["users"]

    return patient

@router.get("/", response_model=List[PatientResponse])
async def get_patients(
    name: Optional[str] = None,
    current_user: dict = Depends(RoleChecker(["admin", "doctor"]))
):
    """
    GET /patients/ — Admin or Doctor only.
    Returns a list of all patient profiles. Pass ?name=John to filter by name.
    """
    return await supabase_service.get_patients(name)


@router.put("/{patient_id}", response_model=PatientResponse)
async def update_patient(
    patient_id: int,
    patient_in: PatientUpdate,
    current_user: dict = Depends(RoleChecker(["admin", "doctor"]))
):
    """
    PUT /patients/{patient_id} — Admin or Doctor only.
    Updates the patient profile for the given patient_id. Only fields provided in the
    request body are changed (partial update). Returns the updated patient record.
    """
    from app.core.supabase import supabase
    from fastapi.concurrency import run_in_threadpool

    result = await run_in_threadpool(
        lambda: supabase.table("patients").select("*").eq("patient_id", patient_id).execute()
    )
    patient = result.data[0] if result.data else None

    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # exclude_unset=True means only fields the caller actually sent are included — others stay unchanged.
    update_data = patient_in.model_dump(exclude_unset=True)
    if "registered_date" in update_data and update_data["registered_date"]:
        # Supabase expects dates as ISO 8601 strings, not Python date objects.
        update_data["registered_date"] = update_data["registered_date"].isoformat()
    update_data["updated_at"] = datetime.utcnow().isoformat()

    result = await run_in_threadpool(
        lambda: supabase.table("patients").update(update_data).eq("patient_id", patient_id).execute()
    )
    return result.data[0] if result.data else {}

@router.delete("/{patient_id}")
async def delete_patient(
    patient_id: int,
    # Deleting patients is a destructive action restricted to admins only.
    current_user: dict = Depends(RoleChecker(["admin"]))
):
    """
    DELETE /patients/{patient_id} — Admin only.
    Deletes the patient's login account from the users table; the patients row is
    removed automatically if the database has a cascade delete rule configured.
    """
    from app.core.supabase import supabase
    from fastapi.concurrency import run_in_threadpool

    # First get the user_id so we can delete the core user account too if needed
    result = await run_in_threadpool(
        lambda: supabase.table("patients").select("*").eq("patient_id", patient_id).execute()
    )
    patient = result.data[0] if result.data else None
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Delete the user account which will cascade to patient if configured,
    # but we'll do both to be safe
    await run_in_threadpool(
        lambda: supabase.table("users").delete().eq("user_id", patient["user_id"]).execute()
    )

    return {"message": "Patient deleted successfully"}
