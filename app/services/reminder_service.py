"""
reminder_service.py

Handles all business logic around patient reminders for the Burjeel Smart Care system.
Responsibilities include:
  - Creating, reading, and updating reminder records in the database.
  - Scanning the database for reminders that are due and dispatching SMS + email notifications.
  - Loading and populating HTML/text message templates from disk.
  - Converting UTC timestamps to the Asia/Muscat timezone before displaying them to patients.
"""

from typing import List, Dict, Any, Optional
from app.schemas import ReminderCreate, ReminderUpdate
from app.core.supabase import supabase
from fastapi.concurrency import run_in_threadpool
from datetime import datetime, timedelta
import pytz

from app.services.unified_reminder_service import process_unified_reminder
from app.schemas.unified_reminder import UnifiedReminderRequest

import logging
import os

# Configure logging
logger = logging.getLogger(__name__)

MUSCAT_TZ = pytz.timezone("Asia/Muscat")

def format_muscat_time(dt_str: str) -> str:
    """
    Convert a UTC datetime string to the Asia/Muscat timezone and return it
    formatted as a human-readable 12-hour clock string (e.g. '2:30 PM').

    Parameters:
        dt_str: An ISO 8601 datetime string, e.g. '2026-05-30T10:00:00Z'.

    Returns:
        A time string in Muscat local time, or the original string if parsing fails.
    """
    try:
        # Replace the trailing 'Z' (which means UTC) with '+00:00' so Python's
        # fromisoformat can understand it — Python < 3.11 does not accept 'Z' directly.
        dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))

        # If the datetime has no timezone information at all, assume it is UTC.
        if dt.tzinfo is None:
            dt = pytz.utc.localize(dt)

        muscat_dt = dt.astimezone(MUSCAT_TZ)
        return muscat_dt.strftime("%I:%M %p")
    except Exception as e:
        logger.error(f"Error formatting Muscat time: {str(e)}")
        return dt_str

def format_muscat_date(dt_str: str) -> str:
    """
    Convert a UTC datetime string to the Asia/Muscat timezone and return it
    formatted as a long-form date string (e.g. 'May 04, 2026').

    Parameters:
        dt_str: An ISO 8601 datetime string, e.g. '2026-05-30T10:00:00Z'.

    Returns:
        A date string in Muscat local time, or the original string if parsing fails.
    """
    try:
        dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = pytz.utc.localize(dt)
        muscat_dt = dt.astimezone(MUSCAT_TZ)
        return muscat_dt.strftime("%B %d, %Y")
    except Exception as e:
        logger.error(f"Error formatting Muscat date: {str(e)}")
        return dt_str

def get_template(template_name: str, ext: str = "html", **kwargs) -> str:
    """
    Load a message template file from disk, replace all named placeholders with
    the provided values, and return the final content string.

    Parameters:
        template_name: The base filename (without extension) of the template, e.g. 'appointment'.
        ext: The file extension — 'html' for email bodies, 'txt' for SMS bodies.
        **kwargs: Key-value pairs where each key matches a {{key}} placeholder in the template.

    Returns:
        The fully populated template string, or a simple fallback string if the file cannot be read.
    """
    template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Send_Body")
    template_path = os.path.join(template_dir, f"{template_name}.{ext}")
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            content = f.read()

        for key, value in kwargs.items():
            # Build the placeholder string in the format {{key}} — the double braces are
            # needed because a single brace is used for Python f-string interpolation.
            placeholder = f"{{{{{key}}}}}"
            logger.debug(f"Attempting to replace {placeholder} with {value}")
            content = content.replace(placeholder, str(value))
        return content
    except Exception as e:
        logger.error(f"Failed to load template {template_name}.{ext}: {str(e)}")
        # Fallback or re-raise
        return f"Content: {str(kwargs)}"


async def _process_reminders(start_dt: datetime, end_dt: datetime) -> Dict[str, Any]:
    """
    Core worker that fetches reminders due within a time window and sends
    SMS + email notifications to each patient.

    Parameters:
        start_dt: The beginning of the time window (timezone-aware UTC datetime).
        end_dt: The end of the time window (timezone-aware UTC datetime).

    Returns:
        A summary dict with 'total_found', 'processed', and 'successful' counts.
    """
    logger.info(f"Processing reminders from {start_dt} to {end_dt}")

    # Fetch reminders in range, joining through patients to reach the user's email address.
    # The nested select "patients(*, users!patients_user_id_fkey(*))" tells Supabase to
    # also return the linked patient row and, inside that, the linked user row.
    result = await run_in_threadpool(
        lambda: supabase.table("reminders")
        .select("*, patients(*, users!patients_user_id_fkey(*))")
        .gte("scheduled_date", start_dt.isoformat())
        .lte("scheduled_date", end_dt.isoformat())
        .execute()
    )
    print(result)
    reminders = result.data if result.data else []
    logger.info(f"Found {len(reminders)} pending reminders")
    
    processed_count = 0
    success_count = 0
    
    for reminder in reminders:
        reminder_id = reminder.get("reminder_id")
        # Handle potential list or dict for joined data
        patient_data = reminder.get("patients")
        if isinstance(patient_data, list):
            patient = patient_data[0] if patient_data else None
        else:
            patient = patient_data
            
        if not patient:
            logger.warning(f"Reminder {reminder_id} has no associated patient data")
            continue
            
        # Email lives in the 'users' table, not 'patients'. Supabase returns the joined
        # row under a key named after the FK constraint; fall back to plain "users" if needed.
        user_data = patient.get("users!patients_user_id_fkey") or patient.get("users")
        if isinstance(user_data, list):
            user = user_data[0] if user_data else None
        else:
            user = user_data
            
        email = user.get("email") if user else None
        phone = patient.get("phone_number")
        
        if not phone or not email:
            logger.warning(f"Reminder {reminder_id} skipped: missing phone ({phone}) or email ({email})")
            continue
            
        logger.debug(f"Processing reminder {reminder_id} for patient {patient.get('patient_id')}")
        
        # Prepare message
        reminder_type = reminder.get("reminder_type", "medication")
        
        # Determine the name to display (either medication name or doctor name)
        # Using 'display_name' column as a generic 'name' field in DB
        display_name = reminder.get("display_name", "item")
        
        # Format date and time for Muscat
        scheduled_dt_str = str(reminder['scheduled_date'])
        formatted_time = format_muscat_time(scheduled_dt_str)
        formatted_date = format_muscat_date(scheduled_dt_str)
        
        if reminder_type == "doctor_visit":
            details = f"Doctor visit appointment with Dr. {display_name}"
            # message = f"Reminder: You have a doctor visit appointment with Dr. {display_name} on {formatted_date} at {formatted_time}. - Burjeel Smart Care"
        else:
            details = f"Please take your medication '{display_name}'"
            # message = f"Reminder: Please take your medication '{display_name}' on {formatted_date} at {formatted_time}. - Burjeel Smart Care"
            
        # Generate HTML email content and SMS text content
        template_name = "appointment" if reminder_type == "doctor_visit" else "medication"
        subject = "Appointment Reminder - Burjeel Smart Care" if reminder_type == "doctor_visit" else "Medication Reminder - Burjeel Smart Care"
        
        email_html = get_template(
            template_name,
            ext="html",
            patient_name=patient.get("full_name", "Patient"),
            doctor_name=display_name if reminder_type == "doctor_visit" else "Doctor",
            medication_name=display_name,
            scheduled_date=formatted_date,
            time=formatted_time,
            reminder_type=reminder_type.replace("_", " ").title(),
            reminder_details=details
        )
        
        sms_text = get_template(
            template_name,
            ext="txt",
            patient_name=patient.get("full_name", "Patient"),
            doctor_name=display_name if reminder_type == "doctor_visit" else "Doctor",
            medication_name=display_name,
            scheduled_date=formatted_date,
            time=formatted_time,
            reminder_type=reminder_type.replace("_", " ").title(),
            reminder_details=details
        )

        # Create unified request
        try:
            request = UnifiedReminderRequest(
                phone_number=phone,
                email_address=email,
                message_content=sms_text,
                email_content=email_html,
                subject=subject
            )
        except Exception as e:
            logger.error(f"Validation failed for reminder {reminder_id}: {str(e)}")
            continue
        
        # Send notifications
        response = await process_unified_reminder(request)
        
        # Update reminder status
        current_success = reminder.get("success_sent") or 0
        current_failed = reminder.get("failed_sent") or 0
        
        if response.overall_success:
            current_success += 1
        else:
            current_failed += 1
        
        logger.info(f"Reminder {reminder_id} result: SMS={response.sms_status.success}, Email={response.email_status.success}")
        
        # Write the updated success/failure counters back to the database so the
        # scheduler can track how many times each reminder has been attempted.
        await run_in_threadpool(
            lambda: supabase.table("reminders")
            .update({
                "success_sent": current_success,
                "failed_sent": current_failed,
                "updated_at": datetime.utcnow().isoformat()
            })
            .eq("reminder_id", reminder["reminder_id"])
            .execute()
        )
        
        processed_count += 1
        if response.overall_success:
            success_count += 1
            
    return {
        "total_found": len(reminders),
        "processed": processed_count,
        "successful": success_count
    }

async def process_today_reminders() -> Dict[str, Any]:
    """
    Trigger notifications for all reminders that fall between right now and midnight UTC today.
    Intended to be called by a scheduled job to send same-day reminders.

    Returns:
        A summary dict with total_found, processed, and successful counts.
    """
    now = datetime.now(pytz.utc)
    # Advance one day and zero out the time components to get exactly midnight at the end of today.
    end_of_today = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return await _process_reminders(now, end_of_today)

async def process_upcoming_reminders() -> Dict[str, Any]:
    """
    Trigger notifications for all reminders due within the next 48 hours.
    Intended to be called by a scheduled job to send advance reminders.

    Returns:
        A summary dict with total_found, processed, and successful counts.
    """
    now = datetime.now(pytz.utc)
    two_days_later = now + timedelta(days=2)
    return await _process_reminders(now, two_days_later)

async def send_issue_notification(reminder: dict, patient: dict, user: dict):
    """
    Send an immediate confirmation notification to a patient when a new reminder (appointment
    or medication) is created for them. Uses the *_issued template variants which have
    different wording than the recurring reminder templates.

    Parameters:
        reminder: The newly created reminder record from the database.
        patient: The patient record associated with the reminder.
        user: The user record (holds the patient's email address).
    """
    if not patient or not user or not user.get("email"):
        return
        
    reminder_type = reminder.get("reminder_type", "medication")
    display_name = reminder.get("display_name", "item")
    phone = patient.get("phone_number")
    email = user.get("email")
    
    # Format date and time for Muscat
    scheduled_dt_str = str(reminder['scheduled_date'])
    formatted_time = format_muscat_time(scheduled_dt_str)
    formatted_date = format_muscat_date(scheduled_dt_str)
    
    if reminder_type == "doctor_visit":
        details = f"Doctor visit appointment with Dr. {display_name}"
        template_name = "appointment_issued"
        subject = "Appointment Created Successfully - Burjeel Smart Care"
    else:
        details = f"Medication '{display_name}' has been issued"
        template_name = "medication_issued"
        subject = "Medication Issued Successfully - Burjeel Smart Care"
        
    email_html = get_template(
        template_name,
        ext="html",
        patient_name=patient.get("full_name", "Patient"),
        doctor_name=display_name if reminder_type == "doctor_visit" else "Doctor",
        medication_name=display_name,
        scheduled_date=formatted_date,
        time=formatted_time,
        reminder_type=reminder_type.replace("_", " ").title(),
        reminder_details=details
    )
    
    sms_text = get_template(
        template_name,
        ext="txt",
        patient_name=patient.get("full_name", "Patient"),
        doctor_name=display_name if reminder_type == "doctor_visit" else "Doctor",
        medication_name=display_name,
        scheduled_date=formatted_date,
        time=formatted_time,
        reminder_type=reminder_type.replace("_", " ").title(),
        reminder_details=details
    )
    
    try:
        request = UnifiedReminderRequest(
            phone_number=phone,
            email_address=email,
            message_content=sms_text,
            email_content=email_html,
            subject=subject
        )
        await process_unified_reminder(request)
    except Exception as e:
        logger.error(f"Failed to send issue notification for reminder {reminder.get('reminder_id')}: {str(e)}")

async def create_reminder(
    reminder_in: ReminderCreate,
    created_by: Optional[int] = None
) -> Dict[str, Any]:
    """
    Validate and persist a new reminder record to the database.

    Parameters:
        reminder_in: A ReminderCreate schema containing the reminder details from the API request.
        created_by: The user_id of the staff member creating this reminder (optional).

    Returns:
        The newly inserted reminder record as a dict from the database.
    """
    reminder_data = reminder_in.model_dump()
    # Convert the Python datetime object to an ISO string, which is what the database expects.
    reminder_data["scheduled_date"] = reminder_data["scheduled_date"].isoformat()
    reminder_data["created_by"] = created_by
    now = datetime.utcnow().isoformat()
    reminder_data["created_at"] = now
    reminder_data["updated_at"] = now
    
    # Remove fields not present in the database 'reminders' table to avoid PGRST204
    # Your schema has: reminder_id, patient_id, display_name, scheduled_date, sent_status, delivery_confirmation, created_at, updated_at, created_by, reminder_type, message_template
    
    # Remove 'message_template' if not needed (it's in the DB but often unused)
    if "message_template" in reminder_data and reminder_data["message_template"] is None:
        del reminder_data["message_template"]
    
    # Ensure reminder_type is correctly set for the DB check constraint
    if "reminder_type" not in reminder_data or not reminder_data["reminder_type"] or reminder_data["reminder_type"] not in ["medication", "doctor_visit"]:
        reminder_data["reminder_type"] = "medication"
    
    result = await run_in_threadpool(
        lambda: supabase.table("reminders").insert(reminder_data).execute()
    )
    db_reminder = result.data[0] if result.data else {}
            
    return db_reminder

async def get_reminder(reminder_id: int) -> Optional[Dict[str, Any]]:
    """
    Retrieve a single reminder by its primary key.

    Parameters:
        reminder_id: The integer primary key of the reminder to look up.

    Returns:
        The reminder record as a dict, or None if not found.
    """
    result = await run_in_threadpool(
        lambda: supabase.table("reminders").select("*").eq("reminder_id", reminder_id).execute()
    )
    return result.data[0] if result.data else None

async def get_reminders_by_patient(patient_id: int) -> List[Dict[str, Any]]:
    """
    Retrieve all reminders associated with a specific patient.

    Parameters:
        patient_id: The numeric ID of the patient whose reminders to fetch.

    Returns:
        A list of reminder dicts; empty list if the patient has no reminders.
    """
    result = await run_in_threadpool(
        lambda: supabase.table("reminders").select("*").eq("patient_id", patient_id).execute()
    )
    return result.data

async def update_reminder(
    reminder_id: int,
    reminder_in: ReminderUpdate
) -> Dict[str, Any]:
    """
    Apply partial updates to an existing reminder record.

    Parameters:
        reminder_id: The numeric ID of the reminder to update.
        reminder_in: A ReminderUpdate schema with only the fields that should change.

    Returns:
        The updated reminder record as a dict, or an empty dict if nothing was changed.
    """
    # exclude_unset=True ensures only the fields the caller explicitly provided are sent,
    # leaving all other fields unchanged in the database.
    update_data = reminder_in.model_dump(exclude_unset=True)
    if "scheduled_date" in update_data and update_data["scheduled_date"]:
        # Convert the datetime object to an ISO string for the database.
        update_data["scheduled_date"] = update_data["scheduled_date"].isoformat()
    update_data["updated_at"] = datetime.utcnow().isoformat()
    
    # Remove fields not present in the database 'reminders' table to avoid PGRST204
    # Your schema has: reminder_id, patient_id, display_name, scheduled_date, sent_status, delivery_confirmation, created_at, updated_at, created_by, reminder_type, message_template
    
    # Remove 'message_template' if not needed (it's in the DB but often unused)
    if "message_template" in update_data and update_data["message_template"] is None:
        del update_data["message_template"]
    
    # Ensure reminder_type is valid if updated
    if "reminder_type" in update_data:
        if not update_data["reminder_type"] or update_data["reminder_type"] not in ["medication", "doctor_visit"]:
            update_data["reminder_type"] = "medication"
    
    result = await run_in_threadpool(
        lambda: supabase.table("reminders").update(update_data).eq("reminder_id", reminder_id).execute()
    )
    return result.data[0] if result.data else {}

async def delete_reminder(reminder_id: int) -> None:
    """
    Permanently delete a reminder record from the database.

    Parameters:
        reminder_id: The numeric ID of the reminder to delete.
    """
    await run_in_threadpool(
        lambda: supabase.table("reminders").delete().eq("reminder_id", reminder_id).execute()
    )
