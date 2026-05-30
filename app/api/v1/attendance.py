"""
Attendance (appointment check-in) endpoints for the Burjeel Smart Care API.

This module tracks whether patients showed up for their scheduled appointments.
Admins and doctors can create and update attendance records.
Any authenticated user can read attendance records, with optional date range filtering.
"""

from datetime import date, datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from app.schemas import AttendanceCreate, AttendanceUpdate, AttendanceResponse
from app.api.deps import get_current_active_user, RoleChecker
from app.core.supabase import supabase
from fastapi.concurrency import run_in_threadpool

router = APIRouter()


@router.post("/", response_model=AttendanceResponse, status_code=status.HTTP_201_CREATED)
async def create_attendance(
    attendance_in: AttendanceCreate,
    current_user: dict = Depends(RoleChecker(["admin", "doctor"]))
):
    """
    POST /attendance/ — Admin or Doctor only.
    Marks a patient as attended (or not) for an appointment on a given date.
    Optionally links the record to an existing reminder. Returns the saved attendance record.
    """
    patient_result = await run_in_threadpool(
        lambda: supabase.table("patients").select("*").eq("patient_id", attendance_in.patient_id).execute()
    )
    if not patient_result.data:
        raise HTTPException(status_code=404, detail="Patient not found")

    # If a reminder_id was provided, validate that it actually exists before linking it.
    if attendance_in.reminder_id:
        reminder_result = await run_in_threadpool(
            lambda: supabase.table("reminders").select("*").eq("reminder_id", attendance_in.reminder_id).execute()
        )
        if not reminder_result.data:
            raise HTTPException(status_code=404, detail="Reminder not found")

    attendance_data = attendance_in.model_dump()
    # Convert the Python date object to an ISO string so Supabase can store it correctly.
    attendance_data["appointment_date"] = attendance_data["appointment_date"].isoformat()
    attendance_data["marked_by"] = current_user["user_id"]
    attendance_data["created_by"] = current_user["user_id"]
    attendance_data["timestamp"] = datetime.utcnow().isoformat()
    attendance_data["created_at"] = datetime.utcnow().isoformat()
    attendance_data["updated_at"] = datetime.utcnow().isoformat()

    result = await run_in_threadpool(
        lambda: supabase.table("attendance").insert(attendance_data).execute()
    )
    return result.data[0] if result.data else {}


@router.get("/", response_model=List[AttendanceResponse])
async def get_attendances(
    patient_id: Optional[int] = None,
    # Query(...) tells FastAPI these are URL query parameters, e.g. ?from_date=2024-01-01
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    current_user: dict = Depends(get_current_active_user)
):
    """
    GET /attendance/ — Any authenticated user.
    Returns attendance records with optional filters: ?patient_id=1, ?from_date=YYYY-MM-DD,
    ?to_date=YYYY-MM-DD. Combine filters to narrow down to a specific patient and date range.
    """
    query = supabase.table("attendance").select("*")

    if patient_id:
        query = query.eq("patient_id", patient_id)
    # gte = "greater than or equal to" — filters records on or after from_date.
    if from_date:
        query = query.gte("appointment_date", from_date.isoformat())
    # lte = "less than or equal to" — filters records on or before to_date.
    if to_date:
        query = query.lte("appointment_date", to_date.isoformat())

    result = await run_in_threadpool(lambda: query.execute())
    return result.data


@router.get("/{attendance_id}", response_model=AttendanceResponse)
async def get_attendance(
    attendance_id: int,
    current_user: dict = Depends(get_current_active_user)
):
    """
    GET /attendance/{attendance_id} — Any authenticated user.
    Returns a single attendance record by ID. Returns 404 if it does not exist.
    """
    result = await run_in_threadpool(
        lambda: supabase.table("attendance").select("*").eq("attendance_id", attendance_id).execute()
    )
    attendance = result.data[0] if result.data else None
    if not attendance:
        raise HTTPException(status_code=404, detail="Attendance not found")
    return attendance


@router.put("/{attendance_id}", response_model=AttendanceResponse)
async def update_attendance(
    attendance_id: int,
    attendance_in: AttendanceUpdate,
    current_user: dict = Depends(RoleChecker(["admin", "doctor"]))
):
    """
    PUT /attendance/{attendance_id} — Admin or Doctor only.
    Updates an existing attendance record (e.g. correcting the status or date).
    Only fields included in the request body are changed.
    """
    result = await run_in_threadpool(
        lambda: supabase.table("attendance").select("*").eq("attendance_id", attendance_id).execute()
    )
    attendance = result.data[0] if result.data else None
    if not attendance:
        raise HTTPException(status_code=404, detail="Attendance not found")

    # exclude_unset=True skips any fields the caller did not send, leaving the DB values untouched.
    update_data = attendance_in.model_dump(exclude_unset=True)
    if "appointment_date" in update_data and update_data["appointment_date"]:
        # Supabase expects dates as ISO 8601 strings, not Python date objects.
        update_data["appointment_date"] = update_data["appointment_date"].isoformat()
    update_data["updated_at"] = datetime.utcnow().isoformat()

    result = await run_in_threadpool(
        lambda: supabase.table("attendance").update(update_data).eq("attendance_id", attendance_id).execute()
    )
    return result.data[0] if result.data else {}
