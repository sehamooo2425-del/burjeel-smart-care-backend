"""
Reminder management endpoints for the Burjeel Smart Care API.

This module handles medication reminders and doctor-visit appointment reminders.
Admins and doctors can create, update, delete, and manually send reminders.
Any authenticated user can view reminders, but the results are scoped by role:
  - Doctors see only reminders they created or are assigned to.
  - Patients see only their own reminders.
  - Admins see everything.
Two public endpoints (/process-today and /process-upcoming) are intended for cron jobs.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from app.schemas import ReminderCreate, ReminderUpdate, ReminderResponse
from app.services import reminder_service, sms_service
from app.api.deps import get_current_active_user, RoleChecker
from app.core.supabase import supabase
from fastapi.concurrency import run_in_threadpool
from datetime import datetime

router = APIRouter()


@router.post("/", response_model=ReminderResponse, status_code=status.HTTP_201_CREATED)
async def create_reminder(
    reminder_in: ReminderCreate,
    # BackgroundTasks lets FastAPI run work after the response is sent, keeping the API fast.
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(RoleChecker(["admin", "doctor"]))
):
    """
    POST /reminders/ — Admin or Doctor only.
    Creates a new reminder (medication or doctor visit) for a patient and immediately
    triggers an SMS/email notification via a background task. Returns the saved reminder.
    """
    patient_result = await run_in_threadpool(
        lambda: supabase.table("patients").select("*").eq("patient_id", reminder_in.patient_id).execute()
    )
    if not patient_result.data:
        raise HTTPException(status_code=404, detail="Patient not found")

    reminder = await reminder_service.create_reminder(
        reminder_in, created_by=current_user["user_id"]
    )

    # Queue the notification to run after the response is returned so the caller is not blocked.
    background_tasks.add_task(send_reminder, reminder["reminder_id"], background_tasks, current_user)

    return reminder


@router.get("/", response_model=List[ReminderResponse])
async def get_reminders(
    patient_id: Optional[int] = None,
    current_user: dict = Depends(get_current_active_user)
):
    """
    GET /reminders/ — Any authenticated user (results are role-scoped).
    Returns a list of reminders. Doctors see only their own or reminders assigned to them.
    Patients always see only their own reminders regardless of the ?patient_id filter.
    """
    query = supabase.table("reminders").select("*")

    if patient_id:
        query = query.eq("patient_id", patient_id)

    if current_user["role"] == "doctor":
        user_id = current_user["user_id"]
        username = current_user["username"]
        # Doctors can see reminders they created OR doctor_visit reminders where they are the named doctor.
        query = query.or_(f"created_by.eq.{user_id},and(reminder_type.eq.doctor_visit,display_name.eq.{username})")
    elif current_user["role"] == "patient":
        # Patients must only ever see their own reminders — look up their patient_id first.
        patient_result = await run_in_threadpool(
            lambda: supabase.table("patients").select("patient_id").eq("user_id", current_user["user_id"]).execute()
        )
        if not patient_result.data:
            return []  # No patient record found
        own_patient_id = patient_result.data[0]["patient_id"]
        # Override any requested patient_id with their own to prevent viewing others' reminders.
        query = supabase.table("reminders").select("*").eq("patient_id", own_patient_id)

    result = await run_in_threadpool(lambda: query.execute())
    return result.data if result.data else []


@router.get("/process-today")
async def process_today_reminders():
    """
    GET /reminders/process-today — Public (no authentication required).
    Intended to be called by a scheduled cron job. Scans for all reminders scheduled
    for today and sends SMS/email notifications to the relevant patients.
    """
    result = await reminder_service.process_today_reminders()
    return result


@router.get("/process-upcoming")
async def process_upcoming_reminders():
    """
    GET /reminders/process-upcoming — Public (no authentication required).
    Intended to be called by a scheduled cron job. Scans for reminders due in the next
    2 days and sends advance SMS/email notifications to patients.
    """
    result = await reminder_service.process_upcoming_reminders()
    return result


@router.get("/{reminder_id}", response_model=ReminderResponse)
async def get_reminder(
    reminder_id: int,
    current_user: dict = Depends(get_current_active_user)
):
    """
    GET /reminders/{reminder_id} — Any authenticated user.
    Fetches a single reminder by its ID. Returns 404 if the reminder does not exist.
    """
    reminder = await reminder_service.get_reminder(reminder_id)
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")
    return reminder


@router.put("/{reminder_id}", response_model=ReminderResponse)
async def update_reminder(
    reminder_id: int,
    reminder_in: ReminderUpdate,
    current_user: dict = Depends(RoleChecker(["admin", "doctor"]))
):
    """
    PUT /reminders/{reminder_id} — Admin or Doctor only.
    Updates an existing reminder with the fields provided in the request body.
    Returns the updated reminder record.
    """
    reminder = await reminder_service.get_reminder(reminder_id)
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")

    return await reminder_service.update_reminder(reminder_id, reminder_in)


@router.delete("/{reminder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reminder(
    reminder_id: int,
    current_user: dict = Depends(RoleChecker(["admin", "doctor"]))
):
    """
    DELETE /reminders/{reminder_id} — Admin or Doctor only.
    Permanently deletes the specified reminder. Returns HTTP 204 (No Content) on success.
    """
    reminder = await reminder_service.get_reminder(reminder_id)
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")

    await reminder_service.delete_reminder(reminder_id)
    return


@router.post("/{reminder_id}/send")
async def send_reminder(
    reminder_id: int,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(RoleChecker(["admin", "doctor"]))
):
    """
    POST /reminders/{reminder_id}/send — Admin or Doctor only.
    Manually triggers an SMS and email notification for a specific reminder.
    Chooses the correct email/SMS template based on reminder type (medication or doctor_visit)
    and whether the reminder was just created. Updates success/failure counters after sending.
    """
    reminder = await reminder_service.get_reminder(reminder_id)
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")

    # Fetch patient with joined user to get email.
    # The "!" syntax specifies the exact foreign key to use, avoiding a Supabase PGRST201 ambiguity error.
    patient_result = await run_in_threadpool(
        lambda: supabase.table("patients")
        .select("*, users!patients_user_id_fkey(*)")
        .eq("patient_id", reminder["patient_id"])
        .execute()
    )

    patient_data = patient_result.data[0] if patient_result.data else None
    if not patient_data:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Supabase may return the joined users row under a key that includes the FK name.
    user_data = patient_data.get("users!patients_user_id_fkey") or patient_data.get("users")
    if isinstance(user_data, list):
        user = user_data[0] if user_data else None
    else:
        user = user_data

    email = user.get("email") if user else None
    phone = patient_data.get("phone_number")

    if not phone or not email:
        raise HTTPException(
            status_code=400,
            detail="Patient missing phone number or email for notification"
        )

    reminder_type = reminder.get("reminder_type", "medication")

    # 'display_name' stores either a medication name or a doctor's name depending on reminder_type.
    display_name = reminder.get("display_name", "item")

    from app.services.reminder_service import get_template, format_muscat_time, format_muscat_date

    # Convert the stored UTC datetime string to a human-readable Muscat (GMT+4) time.
    scheduled_dt_str = str(reminder['scheduled_date'])
    formatted_time = format_muscat_time(scheduled_dt_str)
    formatted_date = format_muscat_date(scheduled_dt_str)

    # A reminder is considered "new" (just issued) if it has never been updated since creation.
    # The '_issued' suffix selects the confirmation template instead of the reminder template.
    is_new = reminder.get("created_at") == reminder.get("updated_at")
    suffix = "_issued" if is_new else ""
    template_name = ("medication" if reminder_type == "medication" else "appointment") + suffix

    # Build a context dict of variables that the HTML/text templates will interpolate.
    context = {
        "patient_name": patient_data.get("full_name", "Patient"),
        "reminder_type": reminder_type.replace("_", " ").title(),
        "scheduled_date": formatted_date,
        "time": formatted_time,
    }

    if reminder_type == "doctor_visit":
        context["doctor_name"] = display_name
        context["reminder_details"] = f"Doctor visit appointment with Dr. {display_name}"
    else:
        context["reminder_details"] = f"Please take your medication '{display_name}'"
        context["medication_name"] = display_name

    email_html = get_template(
        template_name,
        ext="html",
        **context
    )

    sms_text = get_template(
        template_name,
        ext="txt",
        **context
    )

    # Pick an email subject line that reflects whether this is a new booking or a reminder.
    if reminder_type == "doctor_visit":
        subject = "Appointment Created Successfully - Burjeel Smart Care" if is_new else "Appointment Reminder - Burjeel Smart Care"
    else:
        subject = "Medication Issued Successfully - Burjeel Smart Care" if is_new else "Medication Reminder - Burjeel Smart Care"

    from app.services.unified_reminder_service import process_unified_reminder
    from app.schemas.unified_reminder import UnifiedReminderRequest

    request = UnifiedReminderRequest(
        phone_number=phone,
        email_address=email,
        message_content=sms_text,
        email_content=email_html,
        subject=subject
    )

    # Send via both SMS (Twilio) and email (Gmail) through the unified service.
    response = await process_unified_reminder(request)

    # Track how many times notifications have succeeded or failed for this reminder.
    current_success = reminder.get("success_sent") or 0
    current_failed = reminder.get("failed_sent") or 0

    if response.overall_success:
        current_success += 1
    else:
        current_failed += 1

    await run_in_threadpool(
        lambda: supabase.table("reminders")
        .update({
            "success_sent": current_success,
            "failed_sent": current_failed,
            "updated_at": datetime.utcnow().isoformat()
        })
        .eq("reminder_id", reminder_id)
        .execute()
    )

    return {
        "success": response.overall_success,
        "sms": response.sms_status,
        "email": response.email_status
    }
