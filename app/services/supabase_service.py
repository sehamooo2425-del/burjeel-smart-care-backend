"""
supabase_service.py

A low-level data-access layer that wraps the Supabase Python client.
All direct database queries (SELECT, INSERT, UPDATE) go through this class so
the rest of the app has a single, consistent place to talk to the database.

Every method uses run_in_threadpool to avoid blocking FastAPI's async event loop,
because the Supabase Python client makes synchronous (blocking) HTTP calls.
"""

from typing import List, Dict, Any, Optional
from app.core.supabase import supabase
from fastapi.concurrency import run_in_threadpool

class SupabaseService:
    @staticmethod
    async def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
        """
        Query the 'users' table for a single user matching the given username.

        Parameters:
            username: Exact username string to look up.

        Returns:
            The matching user record as a dict, or None if no user was found.
        """
        result = await run_in_threadpool(
            lambda: supabase.table("users").select("*").eq("username", username).execute()
        )
        return result.data[0] if result.data else None

    @staticmethod
    async def create_user(user_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Insert a new row into the 'users' table.

        Parameters:
            user_data: A dict containing all required column values for the new user.

        Returns:
            The newly inserted user record, or an empty dict if the insert failed.
        """
        result = await run_in_threadpool(
            lambda: supabase.table("users").insert(user_data).execute()
        )
        return result.data[0] if result.data else {}

    @staticmethod
    async def get_patients(name: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieve all patient records, optionally filtered by a partial name match.
        Each patient record is enriched with the linked user's username, email, gender,
        and profile picture by joining the 'users' table.

        Parameters:
            name: Optional partial name string for case-insensitive filtering (ilike).

        Returns:
            A list of patient dicts with user fields merged in at the top level.
        """
        # The explicit foreign key name avoids ambiguity when multiple FK relationships
        # exist between 'patients' and 'users'.
        query = supabase.table("patients").select("*, users!patients_user_id_fkey(username, email, gender, profile_picture_url)")
        if name:
            # ilike performs a case-insensitive LIKE search; % are wildcard characters.
            query = query.ilike("full_name", f"%{name}%")

        result = await run_in_threadpool(lambda: query.execute())
        data = result.data if result.data else []

        # Flatten the nested users dict into the patient dict for easier frontend consumption
        for patient in data:
            if "users" in patient and patient["users"]:
                # Supabase returns joined rows as a list for one-to-many or a dict for one-to-one.
                user_info = patient["users"][0] if isinstance(patient["users"], list) else patient["users"]
                patient["username"] = user_info.get("username")
                patient["email"] = user_info.get("email")
                patient["gender"] = user_info.get("gender")
                patient["profile_picture_url"] = user_info.get("profile_picture_url")
                # Remove the nested key so callers receive a flat dict.
                del patient["users"]

        return data

    @staticmethod
    async def create_patient(patient_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Insert a new row into the 'patients' table.

        Parameters:
            patient_data: A dict containing all required column values for the new patient.

        Returns:
            The newly inserted patient record, or an empty dict if the insert failed.
        """
        result = await run_in_threadpool(
            lambda: supabase.table("patients").insert(patient_data).execute()
        )
        return result.data[0] if result.data else {}

    @staticmethod
    async def get_reminders(patient_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Fetch all reminders, or only those belonging to a specific patient.

        Parameters:
            patient_id: Optional patient ID to filter results; omit for all reminders.

        Returns:
            A list of reminder dicts from the 'reminders' table.
        """
        query = supabase.table("reminders").select("*")
        if patient_id:
            query = query.eq("patient_id", patient_id)

        result = await run_in_threadpool(lambda: query.execute())
        return result.data

    @staticmethod
    async def create_reminder(reminder_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Insert a new reminder row into the 'reminders' table.

        Parameters:
            reminder_data: A dict containing all required column values for the reminder.

        Returns:
            The newly inserted reminder record, or an empty dict if the insert failed.
        """
        result = await run_in_threadpool(
            lambda: supabase.table("reminders").insert(reminder_data).execute()
        )
        return result.data[0] if result.data else {}

    @staticmethod
    async def get_attendance_report(from_date: Optional[str] = None, to_date: Optional[str] = None) -> Dict[str, Any]:
        """
        Calculate a basic attendance report for appointments within an optional date range.

        Parameters:
            from_date: ISO date string for the start of the range (inclusive).
            to_date: ISO date string for the end of the range (inclusive).

        Returns:
            A dict with total_attendances, attendance_rate (%), and the raw data rows.
        """
        # This is a simplified version; more complex reporting may need additional logic.
        query = supabase.table("attendance").select("*")
        if from_date:
            # gte = "greater than or equal to" — filters rows on or after from_date.
            query = query.gte("appointment_date", from_date)
        if to_date:
            # lte = "less than or equal to" — filters rows on or before to_date.
            query = query.lte("appointment_date", to_date)

        result = await run_in_threadpool(lambda: query.execute())
        data = result.data

        total = len(data)
        came = len([r for r in data if r.get("status") == "came"])
        # Guard against division by zero when there are no attendance records.
        rate = (came / total * 100) if total > 0 else 0

        return {
            "total_attendances": total,
            "attendance_rate": round(rate, 2),
            "data": data
        }

supabase_service = SupabaseService()
