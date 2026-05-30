"""
report_service.py

Generates summary reports for hospital management dashboards.
Currently provides two reports:
  - Attendance: counts how many patients showed up vs. did not for their appointments.
  - Reminders: counts how many reminders were sent successfully, are still pending, or failed.
"""

from datetime import date
from typing import Optional, Dict, Any
from app.core.supabase import supabase
from fastapi.concurrency import run_in_threadpool

async def get_attendance_report(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None
) -> Dict[str, Any]:
    """
    Query the 'attendance' table and return a breakdown of patient attendance
    along with an overall attendance rate percentage.

    Parameters:
        from_date: Optional start date to filter records (inclusive).
        to_date: Optional end date to filter records (inclusive).

    Returns:
        A dict with counts for 'came' and 'not came', plus 'total_attendances'
        and 'attendance_rate' (rounded to 2 decimal places).
    """
    # Only fetch the 'status' column — we don't need any other data for this report,
    # which keeps the response payload small.
    query = supabase.table("attendance").select("status")

    if from_date:
        # gte = greater than or equal to; isoformat() converts the date to 'YYYY-MM-DD'.
        query = query.gte("appointment_date", from_date.isoformat())
    if to_date:
        # lte = less than or equal to.
        query = query.lte("appointment_date", to_date.isoformat())

    result = await run_in_threadpool(lambda: query.execute())
    data = result.data

    report = {"came": 0, "not came": 0}
    for item in data:
        status = item.get("status")
        if status in report:
            report[status] += 1

    total = sum(report.values())
    # Guard against division by zero when no attendance records exist in the date range.
    attendance_rate = (report["came"] / total * 100) if total > 0 else 0

    # The ** operator unpacks the report dict so 'came' and 'not came' appear at the
    # top level of the returned dict alongside the computed summary fields.
    return {
        **report,
        "total_attendances": total,
        "attendance_rate": round(attendance_rate, 2)
    }


async def get_reminders_report() -> Dict[str, Any]:
    """
    Query the 'reminders' table and return a breakdown of reminder delivery statuses
    along with an overall success rate percentage.

    Returns:
        A dict with counts for 'pending', 'sent', and 'failed' reminders, plus
        'total' and 'success_rate' (rounded to 2 decimal places).
    """
    # Only fetch the 'sent_status' column to keep the query efficient.
    result = await run_in_threadpool(
        lambda: supabase.table("reminders").select("sent_status").execute()
    )
    data = result.data

    report = {"pending": 0, "sent": 0, "failed": 0}
    for item in data:
        status = item.get("sent_status")
        if status in report:
            report[status] += 1

    total = len(data)
    # Guard against division by zero when there are no reminder records at all.
    success_rate = (report["sent"] / total * 100) if total > 0 else 0

    return {
        **report,
        "total": total,
        "success_rate": round(success_rate, 2)
    }
