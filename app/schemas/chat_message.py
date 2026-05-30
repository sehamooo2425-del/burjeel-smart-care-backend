"""
schemas/chat_message.py — Pydantic data shapes for in-app chat messages.

These schemas define the structure of messages exchanged between users
(e.g. a patient messaging their doctor) through the real-time chat feature.
The sender is never part of the request body — it is always determined from
the authenticated user's token on the server side.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class ChatMessageBase(BaseModel):
    """
    Minimal fields required to describe a chat message.

    receiver_id is Optional to allow for potential broadcast or system
    messages that are not directed at a single user.
    """
    receiver_id: Optional[int] = None  # The user_id of the message recipient.
    message_text: str                   # The actual content of the message.


class ChatMessageCreate(ChatMessageBase):
    """
    Schema for sending a new chat message (the request body).

    The sender's identity is derived from the JWT token, not included here,
    so no extra fields are needed beyond ChatMessageBase.
    """
    pass


class ChatMessageUpdate(BaseModel):
    """
    Schema for updating a message — currently only supports marking it as read.

    Keeping the update schema narrow prevents clients from editing message text
    after it has been sent, which protects message integrity.
    """
    is_read: Optional[bool] = None  # Set to True when the recipient opens the message.


class ChatMessageResponse(ChatMessageBase):
    """
    Schema for chat message data returned to the client.

    Adds server-assigned fields that the client needs to display a message
    thread correctly: who sent it, when, and whether it has been read.
    """
    message_id: int    # Database-generated primary key for this message.
    sender_id: int     # user_id of the user who sent the message (set server-side from the token).
    timestamp: datetime  # Exact date and time the message was created.
    is_read: bool        # False by default; flipped to True when the recipient reads it.
    created_at: datetime
    updated_at: datetime

    class Config:
        # Allows Pydantic to populate this schema from ORM model instances.
        from_attributes = True
