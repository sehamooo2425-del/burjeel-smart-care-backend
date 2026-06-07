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

    # Treat an empty string the same as no email — UserCreate's EmailStr validator
    # rejects "" so we must convert it to None before constructing the object.
    email = patient_in.email if patient_in.email and patient_in.email.strip() else None
    user_in = UserCreate(
        username=patient_in.username,
        email=email,
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
    current_user: dict = Depends(RoleChecker(["admin"]))
):
    """
    DELETE /patients/{patient_id} — Admin only.
    Removes the patient and their login account in FK-safe order:
    attendance → reminders → chat messages → patients → users.
    The database FK constraints do not have CASCADE DELETE, so we must
    delete child rows manually before removing the parent rows.
    """
    from app.core.supabase import supabase
    from fastapi.concurrency import run_in_threadpool

    result = await run_in_threadpool(
        lambda: supabase.table("patients").select("patient_id, user_id").eq("patient_id", patient_id).execute()
    )
    patient = result.data[0] if result.data else None
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    uid = patient["user_id"]

    # 1. Attendance records reference patient_id.
    await run_in_threadpool(lambda: supabase.table("attendance").delete().eq("patient_id", patient_id).execute())
    # 2. Reminders reference patient_id.
    await run_in_threadpool(lambda: supabase.table("reminders").delete().eq("patient_id", patient_id).execute())
    # 3. Chat messages reference user_id (as sender or receiver).
    await run_in_threadpool(lambda: supabase.table("chat_messages").delete().eq("sender_id", uid).execute())
    await run_in_threadpool(lambda: supabase.table("chat_messages").delete().eq("receiver_id", uid).execute())
    # 4. Patient profile row.
    await run_in_threadpool(lambda: supabase.table("patients").delete().eq("patient_id", patient_id).execute())
    # 5. User account — safe to delete now that all child rows are gone.
    await run_in_threadpool(lambda: supabase.table("users").delete().eq("user_id", uid).execute())

    return {"message": "Patient deleted successfully"}
