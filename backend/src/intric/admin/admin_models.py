from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl


class PrivacyPolicy(BaseModel):
    url: Optional[HttpUrl] = None


class UserStateListItem(BaseModel):
    """Minimal user information for state-based list operations"""
    username: str = Field(
        description="User's unique username",
        examples=["jane.smith"]
    )
    email: str = Field(
        description="User's email address",
        examples=["jane.smith@municipality.se"]
    )
    state: str = Field(
        description="User's current state",
        examples=["inactive"]
    )
    state_changed_at: datetime = Field(
        description="When the user state was last changed",
        examples=["2025-09-10T08:30:00Z"]
    )


class UserDeletedListItem(BaseModel):
    """User information for deleted users list operations"""
    username: str = Field(
        description="User's unique username",
        examples=["former.employee"]
    )
    email: str = Field(
        description="User's email address", 
        examples=["former.employee@municipality.se"]
    )
    state: str = Field(
        description="User's current state (always 'deleted' for this list)",
        examples=["deleted"]
    )
    deleted_at: datetime = Field(
        description="When the user was deleted (for external tracking)",
        examples=["2025-08-15T14:20:00Z"]
    )
