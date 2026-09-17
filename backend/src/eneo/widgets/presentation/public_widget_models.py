# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from eneo.widgets.domain.widget import (
    BotProtection,
    WidgetLanguage,
    WidgetTexts,
    WidgetTheme,
)


class WidgetPublicConfig(BaseModel):
    """What the embed page needs to render. Display fields only — no origins,
    limits beyond the question length, internal ids or model names."""

    public_id: str
    name: str
    texts: WidgetTexts
    theme: WidgetTheme
    language: WidgetLanguage
    bot_protection: BotProtection
    max_question_chars: int
    token_generation: int


class WidgetChallenge(BaseModel):
    """ALTCHA v2 challenge as produced by the ``altcha`` library."""

    model_config = ConfigDict(extra="allow")

    parameters: dict[str, Any]
    signature: str


class VisitorSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visitor_id: Optional[UUID] = Field(
        default=None,
        description="Pseudonymous visitor id from a previous session on this site.",
    )
    altcha: Optional[str] = Field(
        default=None,
        max_length=4096,
        description="Base64 ALTCHA payload for a new or expired visitor.",
    )
    previous_token: Optional[str] = Field(
        default=None,
        max_length=4096,
        description="A still-valid or recently expired visitor token to rotate silently.",
    )


class WidgetAsk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=8_000)
    session_id: Optional[UUID] = Field(
        default=None, description="Continue one of the visitor's own sessions."
    )


class VisitorSession(BaseModel):
    token: str
    expires_in: int = Field(description="Seconds until the token expires.")
    visitor_id: UUID
