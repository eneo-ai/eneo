"""Request models of the insights chat endpoints."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class InsightSelectedRange(BaseModel):
    """The Insights tab's date picker, as inclusive local calendar dates."""

    start: date
    end: date

    @model_validator(mode="after")
    def _ordered(self) -> "InsightSelectedRange":
        if self.end < self.start:
            raise ValueError("selected_range.end must not be before start")
        return self


class InsightChatContinueRequest(BaseModel):
    """Follow-up turn on an existing insights conversation."""

    question: str = Field(min_length=1)
    stream: bool = False
    selected_range: InsightSelectedRange | None = None


class InsightChatStartRequest(BaseModel):
    """Start a new insights conversation about one assistant or group chat."""

    assistant_id: UUID | None = None
    group_chat_id: UUID | None = None
    question: str = Field(min_length=1)
    timezone: str = Field(default="UTC", max_length=64)
    stream: bool = False
    selected_range: InsightSelectedRange | None = None

    @model_validator(mode="after")
    def _exactly_one_target(self) -> "InsightChatStartRequest":
        if (self.assistant_id is None) == (self.group_chat_id is None):
            raise ValueError("Provide exactly one of assistant_id or group_chat_id")
        return self
