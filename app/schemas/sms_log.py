from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class SMSLogBase(BaseModel):
    reminder_id: int
    gateway_response: Optional[str] = None


class SMSLogCreate(SMSLogBase):
    pass


class SMSLogResponse(SMSLogBase):
    log_id: int
    sent_timestamp: datetime
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
