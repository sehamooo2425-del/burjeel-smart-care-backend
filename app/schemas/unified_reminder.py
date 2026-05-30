from typing import Optional
from pydantic import BaseModel, EmailStr, Field
from datetime import datetime

class UnifiedReminderRequest(BaseModel):
    phone_number: str = Field(..., pattern=r'^\+?[1-9]\d{1,14}$')
    email_address: EmailStr
    message_content: str = Field(..., min_length=1, max_length=1000)
    email_content: Optional[str] = None
    subject: Optional[str] = "Reminder - Burjeel Smart Care"
    scheduled_time: Optional[datetime] = None

class ServiceStatus(BaseModel):
    success: bool
    message: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class UnifiedReminderResponse(BaseModel):
    sms_status: ServiceStatus
    email_status: ServiceStatus
    overall_success: bool
