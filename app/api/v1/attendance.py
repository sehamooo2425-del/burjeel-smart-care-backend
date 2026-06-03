"""
Attendance (appointment check-in) endpoints for the Burjeel Smart Care API.

This module tracks whether patients showed up for their scheduled appointments.
Admins and doctors can create and update attendance records.
Any authenticated user can read attendance records, with optional date range filtering.
"""

from datetime import date, datetime, timedelta, timezone
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

    Rules enforced:
    - Patient must exist.
    - reminder_id must be provided and refer to a doctor_visit reminder for this patient on this date.
    - Doctors can only mark appointments where reminder.display_name matches their username.
    - Each reminder can only be marked once (no duplicate attendance per appointment).
    """
    # 1. Patient must exist.
    patient_result = await run_in_threadpool(
        lambda: supabase.table("patients").select("patient_id").eq("patient_id", attendance_in.patient_id).execute()
    )
    if not patient_result.data:
        raise HTTPException(status_code=404, detail="Patient not found.")

    # 2. The caller must specify which appointment they are marking.
    if not attendance_in.reminder_id:
        raise HTTPException(status_code=400, detail="Please select an appointment (reminder_id is required).")

    # 3. Load and validate the specified reminder.
    reminder_result = await run_in_threadpool(
        lambda: supabase.table("reminders")
        .select("reminder_id, patient_id, reminder_type, scheduled_date, display_name")
        .eq("reminder_id", attendance_in.reminder_id)
        .execute()
    )
    if not reminder_result.data:
        raise HTTPException(status_code=404, detail="Appointment reminder not found.")
    reminder = reminder_result.data[0]

    if reminder["patient_id"] != attendance_in.patient_id:
        raise HTTPException(status_code=400, detail="This reminder does not belong to the selected patient.")
    if reminder["reminder_type"] != "doctor_visit":
        raise HTTPException(status_code=400, detail="Attendance can only be marked for doctor_visit appointments.")

    # 4. Confirm the reminder's scheduled_date falls within the selected appointment_date (UTC).
    #    scheduled_date is stored as a timezone-aware datetime string, e.g. "2026-05-31T14:00:00+00:00".
    scheduled_dt = datetime.fromisoformat(reminder["scheduled_date"].replace("Z", "+00:00"))
    if scheduled_dt.tzinfo is None:
        scheduled_dt = scheduled_dt.replace(tzinfo=timezone.utc)
    day_start = datetime(
        attendance_in.appointment_date.year,
        attendance_in.appointment_date.month,
        attendance_in.appointment_date.day,
        tzinfo=timezone.utc
    )
    day_end = day_start + timedelta(days=1)
    if not (day_start <= scheduled_dt < day_end):
        raise HTTPException(status_code=400, detail="This reminder is not scheduled for the selected date.")

    # 5. Doctors may only mark attendance for appointments where they are the assigned doctor.
    if current_user["role"] == "doctor" and reminder["display_name"] != current_user["username"]:
        raise HTTPException(status_code=403, detail="Doctors can only mark attendance for their own appointments.")

    # 6. Prevent double-marking — each appointment (reminder) can only be recorded once.
    existing_result = await run_in_threadpool(
        lambda: supabase.table("attendance")
        .select("attendance_id")
        .eq("reminder_id", attendance_in.reminder_id)
        .execute()
    )
    if existing_result.data:
        raise HTTPException(status_code=409, detail="Attendance has already been marked for this appointment.")

    # 7. All checks passed — insert the attendance record.
    attendance_data = attendance_in.model_dump()
    attendance_data["appointment_date"] = attendance_in.appointment_date.isoformat()
    attendance_data["marked_by"]        = current_user["user_id"]
    attendance_data["created_by"]       = current_user["user_id"]
    attendance_data["timestamp"]        = datetime.utcnow().isoformat()
    attendance_data["created_at"]       = datetime.utcnow().isoformat()
    attendance_data["updated_at"]       = datetime.utcnow().isoformat()

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


@router.delete("/{attendance_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attendance(
    attendance_id: int,
    current_user: dict = Depends(RoleChecker(["admin", "doctor"]))
):
    """
    DELETE /attendance/{attendance_id} — Admin or Doctor only.
    Permanently removes an attendance record. Returns HTTP 204 on success.
    """
    result = await run_in_threadpool(
        lambda: supabase.table("attendance").select("attendance_id").eq("attendance_id", attendance_id).execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Attendance record not found.")

    await run_in_threadpool(
        lambda: supabase.table("attendance").delete().eq("attendance_id", attendance_id).execute()
    )


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
