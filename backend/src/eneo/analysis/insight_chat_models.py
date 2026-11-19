"""Request and response models of the insights chat endpoints."""

from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from eneo.ai_models.completion_models.completion_model import CompletionModelPublic

_STREAM_DESCRIPTION = (
    "Always true: every answer is streamed as the version 3 UI Message Stream "
    "of the chat API."
)
_MODEL_DESCRIPTION = (
    "The completion model that answers this turn, one of those the models "
    "route lists for the target; 400 insights_model_not_allowed for any other. "
    "Omitted: {omitted}"
)


class InsightSelectedRange(BaseModel):
    """The Insights tab's period picker, as inclusive local calendar dates."""

    start: date
    end: date

    @model_validator(mode="after")
    def _ordered(self) -> "InsightSelectedRange":
        if self.end < self.start:
            raise ValueError("selected_range.end must not be before start")
        return self


class InsightChatContinueRequest(BaseModel):
    """A follow-up question in an existing insights conversation."""

    question: str = Field(min_length=1)
    stream: Literal[True] = Field(default=True, description=_STREAM_DESCRIPTION)
    selected_range: InsightSelectedRange | None = None
    completion_model_id: UUID | None = Field(
        default=None,
        description=_MODEL_DESCRIPTION.format(
            omitted=(
                "the model of the conversation's latest turn while it may still "
                "answer, else the default."
            )
        ),
    )


class InsightChatStartRequest(BaseModel):
    """Start a new insights conversation about one assistant or group chat."""

    assistant_id: UUID | None = None
    group_chat_id: UUID | None = None
    question: str = Field(min_length=1)
    timezone: str = Field(default="UTC", max_length=64)
    stream: Literal[True] = Field(default=True, description=_STREAM_DESCRIPTION)
    selected_range: InsightSelectedRange | None = None
    completion_model_id: UUID | None = Field(
        default=None,
        description=_MODEL_DESCRIPTION.format(omitted="the default."),
    )

    @model_validator(mode="after")
    def _exactly_one_target(self) -> "InsightChatStartRequest":
        if (self.assistant_id is None) == (self.group_chat_id is None):
            raise ValueError("Provide exactly one of assistant_id or group_chat_id")
        return self


class InsightChatModels(BaseModel):
    """The completion models that may answer an analysis of one target."""

    items: list[CompletionModelPublic] = Field(
        description=(
            "Every model enabled in the target's space that is accessible, "
            "supports tool calling and meets the space's security "
            "classification. Empty when none does."
        )
    )
    default_model_id: UUID | None = Field(
        description=(
            "The model a turn uses when none is chosen: the assistant's own "
            "model when it is listed, else the space's default among the listed "
            "ones. Null when the list is empty."
        )
    )
