"""
Chat endpoints for the Burjeel Smart Care API.

This module supports real-time messaging between users via WebSocket connections,
as well as REST endpoints for fetching message history, listing conversations,
posting messages via HTTP, and marking messages as read.

All users (any role) can chat with each other once authenticated.
A background email notification is sent to the recipient when a new message arrives.
"""

from typing import Dict, List, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from app.schemas import ChatMessageResponse
from app.api.deps import get_current_user_websocket, get_current_active_user, RoleChecker
from app.core.supabase import supabase
from fastapi.concurrency import run_in_threadpool
from datetime import datetime
from pydantic import BaseModel
from app.schemas.chat_message import ChatMessageCreate
import asyncio
from app.core.gmail_service import send_google_email
from app.services.reminder_service import get_template
from app.services.auth_service import get_user_by_id

async def send_chat_notification(sender: dict, receiver_id: int):
    """
    Background helper that emails the message recipient when they have unread chat messages.
    Silently logs and swallows any error so a failed email never disrupts the chat flow.
    """
    try:
        receiver = await get_user_by_id(receiver_id)
        if not receiver or not receiver.get("email"):
            return

        # Count how many unread messages the receiver currently has so we can show it in the email.
        result = await run_in_threadpool(
            lambda: supabase.table("chat_messages")
            .select("message_id", count="exact")
            .eq("receiver_id", receiver_id)
            .eq("is_read", False)
            .execute()
        )

        # Fall back to 1 if the DB did not return a count (e.g. older Supabase client versions).
        unread_count = result.count if hasattr(result, 'count') and result.count is not None else 1

        email_html = get_template(
            "chat_notification",
            ext="html",
            recipient_name=receiver.get("username", "User"),
            sender_role=sender.get("role", "User").capitalize(),
            sender_name=sender.get("username", "Someone"),
            unread_count=unread_count
        )

        await run_in_threadpool(send_google_email, [receiver["email"]], "New Chat Message - Burjeel Smart Care", email_html)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to send chat notification: {str(e)}")


router = APIRouter()


class ConnectionManager:
    """
    Manages all active WebSocket connections, keyed by user_id.
    This allows the server to push messages directly to a specific connected user.
    """

    def __init__(self):
        # Maps user_id -> open WebSocket so we can find any user's connection instantly.
        self.active_connections: Dict[int, WebSocket] = {}

    async def connect(self, websocket: WebSocket, user_id: int):
        """Perform the WebSocket handshake and register the connection for this user."""
        await websocket.accept()
        self.active_connections[user_id] = websocket

    def disconnect(self, user_id: int):
        """Remove a user's connection when they disconnect or the socket is closed."""
        if user_id in self.active_connections:
            del self.active_connections[user_id]

    async def send_personal_message(self, message: dict, user_id: int):
        """Send a JSON message to a specific user if they are currently connected."""
        if user_id in self.active_connections:
            await self.active_connections[user_id].send_json(message)

    async def broadcast(self, message: dict):
        """Send a JSON message to every currently connected user."""
        for connection in self.active_connections.values():
            await connection.send_json(message)


# Global singleton so all requests share the same connection registry.
manager = ConnectionManager()


@router.websocket("/ws/{user_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    user_id: int
):
    """
    WebSocket /chat/ws/{user_id} — Any authenticated user.
    Keeps a persistent two-way connection open for real-time messaging.
    The client sends JSON with 'receiver_id' and 'message_text'; the server saves the
    message to the DB and pushes it to both the sender and the receiver immediately.
    An email notification is also queued in the background for the recipient.
    """
    # Validate the JWT token sent during the WebSocket handshake.
    current_user = await get_current_user_websocket(websocket)
    if not current_user:
        return  # Connection is closed inside get_current_user_websocket if auth fails.

    await manager.connect(websocket, current_user["user_id"])

    try:
        # Keep listening for incoming messages until the client disconnects.
        while True:
            data = await websocket.receive_json()

            receiver_id = data.get("receiver_id")
            message_text = data.get("message_text")

            if message_text:
                message_data = {
                    "sender_id": current_user["user_id"],
                    "receiver_id": receiver_id,
                    "message_text": message_text,
                    "created_by": current_user["user_id"],
                    "timestamp": datetime.utcnow().isoformat(),
                    "created_at": datetime.utcnow().isoformat(),
                    "updated_at": datetime.utcnow().isoformat(),
                    "is_read": False
                }

                # Persist the message to the database before pushing it to clients.
                result = await run_in_threadpool(
                    lambda: supabase.table("chat_messages").insert(message_data).execute()
                )
                db_message = result.data[0] if result.data else {}

                message_response = {
                    "message_id": db_message.get("message_id"),
                    "sender_id": db_message.get("sender_id"),
                    "receiver_id": db_message.get("receiver_id"),
                    "message_text": db_message.get("message_text"),
                    "timestamp": db_message.get("timestamp"),
                    "is_read": db_message.get("is_read")
                }

                # Echo the saved message back to the sender so their UI can confirm it was stored.
                await manager.send_personal_message(message_response, current_user["user_id"])

                if receiver_id:
                    # Push the message to the receiver if they are currently online.
                    await manager.send_personal_message(message_response, receiver_id)
                    # Also send an email notification in the background (non-blocking).
                    asyncio.create_task(send_chat_notification(current_user, receiver_id))

    except WebSocketDisconnect:
        # Clean up the connection registry when the client closes the socket.
        manager.disconnect(current_user["user_id"])


@router.get("/conversations/", response_model=List[Dict])
async def get_user_conversations(
    current_user: dict = Depends(get_current_active_user)
):
    """
    GET /chat/conversations/ — Any authenticated user.
    Returns every other user in the system along with the message history shared with each,
    the timestamp of the last message, and a count of unread messages from each user.
    Conversations are sorted newest-first; users with no messages appear at the end.
    """
    # Fetch every user except the currently logged-in one to build the contact list.
    all_users_result = await run_in_threadpool(
        lambda: supabase.table("users")
        .select("user_id, username, role, account_status")
        .neq("user_id", current_user["user_id"])
        .execute()
    )

    if not all_users_result.data:
        return []

    # Retrieve all messages where the current user is either the sender or the receiver.
    messages_result = await run_in_threadpool(
        lambda: supabase.table("chat_messages")
        .select("*")
        .or_(f"sender_id.eq.{current_user['user_id']},receiver_id.eq.{current_user['user_id']}")
        .order("timestamp", desc=True)
        .execute()
    )

    messages_data = messages_result.data or []

    # Group messages by the other participant's user_id for easy lookup below.
    conversations_by_user = {}
    for msg in messages_data:
        # The "other" person is whichever side is not the current user.
        other_id = msg["receiver_id"] if msg["sender_id"] == current_user["user_id"] else msg["sender_id"]
        if other_id not in conversations_by_user:
            conversations_by_user[other_id] = []
        conversations_by_user[other_id].append(msg)

    result_list = []
    for user_data in all_users_result.data:
        user_id = user_data["user_id"]
        messages = conversations_by_user.get(user_id, [])

        result_list.append({
            "other_participant": user_data,
            "messages": sorted(messages, key=lambda x: x["timestamp"]) if messages else [],
            # messages[0] is the most recent because we ordered by timestamp desc above.
            "last_message_time": messages[0]["timestamp"] if messages else None,
            # Count only messages sent TO the current user that have not been read yet.
            "unread_count": len([m for m in messages if m["receiver_id"] == current_user["user_id"] and not m["is_read"]])
        })

    # Tuples sort lexicographically: (True, timestamp) sorts after (False, ""), putting
    # users with messages before users with no messages, and newest messages first.
    return sorted(result_list, key=lambda x: (x["last_message_time"] is not None, x["last_message_time"] or ""), reverse=True)


@router.get("/messages/", response_model=List[ChatMessageResponse])
async def get_chat_messages(
    with_user_id: Optional[int] = None,
    current_user: dict = Depends(get_current_active_user)
):
    """
    GET /chat/messages/ — Any authenticated user (results are role-scoped).
    Without a filter, staff roles see all messages; patients see only their own.
    Pass ?with_user_id=5 to retrieve the conversation thread with a specific user.
    """
    if with_user_id:
        # The OR condition fetches messages in both directions of the conversation.
        result = await run_in_threadpool(
            lambda: supabase.table("chat_messages")
            .select("*")
            .or_(f"and(sender_id.eq.{current_user['user_id']},receiver_id.eq.{with_user_id}),and(sender_id.eq.{with_user_id},receiver_id.eq.{current_user['user_id']})")
            .order("timestamp")
            .execute()
        )
    else:
        if current_user["role"] in ["admin", "doctor"]:
            # Staff can see the full message log for moderation or audit purposes.
            result = await run_in_threadpool(
                lambda: supabase.table("chat_messages").select("*").order("timestamp").execute()
            )
        else:
            # Patients only see their own messages
            result = await run_in_threadpool(
                lambda: supabase.table("chat_messages")
                .select("*")
                .or_(f"sender_id.eq.{current_user['user_id']},receiver_id.eq.{current_user['user_id']}")
                .order("timestamp")
                .execute()
            )

    return result.data

@router.post("/messages/", response_model=ChatMessageResponse)
async def create_chat_message(
    message_in: ChatMessageCreate,
    current_user: dict = Depends(get_current_active_user)
):
    """
    POST /chat/messages/ — Any authenticated user.
    HTTP alternative to the WebSocket for sending a single chat message.
    Saves the message to the database and queues an email notification to the recipient.
    Returns the saved message record.
    """
    message_data = {
        "sender_id": current_user["user_id"],
        "receiver_id": message_in.receiver_id,
        "message_text": message_in.message_text,
        "created_by": current_user["user_id"],
        "timestamp": datetime.utcnow().isoformat(),
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
        "is_read": False
    }

    result = await run_in_threadpool(
        lambda: supabase.table("chat_messages").insert(message_data).execute()
    )

    db_message = result.data[0] if result.data else {}
    if message_in.receiver_id:
        # Fire the email notification asynchronously so the API response is not delayed.
        asyncio.create_task(send_chat_notification(current_user, message_in.receiver_id))
    return db_message


class MarkReadRequest(BaseModel):
    """Request body for marking messages as read. Contains only the sender whose messages to mark."""
    sender_id: int


@router.put("/messages/read")
async def mark_messages_read(
    request: MarkReadRequest,
    current_user: dict = Depends(get_current_active_user)
):
    """
    PUT /chat/messages/read — Any authenticated user.
    Marks all unread messages from a specific sender as read for the current user.
    Call this when the user opens a conversation to clear the unread badge.
    Returns the count of messages that were updated.
    """
    result = await run_in_threadpool(
        lambda: supabase.table("chat_messages")
        .update({"is_read": True})
        # Only mark messages sent TO the current user FROM the given sender.
        .eq("sender_id", request.sender_id)
        .eq("receiver_id", current_user["user_id"])
        # Skip rows that are already read — avoids unnecessary DB writes.
        .eq("is_read", False)
        .execute()
    )
    return {"success": True, "marked_count": len(result.data) if result.data else 0}
