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
    show_sources: bool = Field(
        description="False when answers are shown without citations or a source list."
    )
    single_turn: bool = Field(
        description=(
            "True when the widget stores nothing after the answer: no follow-up"
            " questions, feedback or restore; every question starts a new"
            " conversation."
        )
    )
    frame_ancestors: list[str] = Field(
        description=(
            "CSP host sources the embed page may be framed by. Mirrors the"
            " frame-ancestors response header, which is public anyway."
        )
    )


class WidgetChallenge(BaseModel):
    """ALTCHA v2 challenge as produced by the ``altcha`` library."""

    model_config = ConfigDict(extra="allow")

    parameters: dict[str, Any]
    signature: str


class VisitorSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visitor_id: Optional[UUID] = Field(
        default=None,
        description=(
            "Pseudonymous visitor id issued earlier for this widget. Honoured"
            " only together with its visitor_key; otherwise a new id is issued."
        ),
    )
    visitor_key: Optional[str] = Field(
        default=None,
        max_length=64,
        description="The key that came with visitor_id when it was issued.",
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
    visitor_key: str = Field(
        description=(
            "Proof that the server issued visitor_id for this widget. Send both"
            " when minting again after the token's grace window to keep the"
            " pseudonym and its conversations."
        )
    )
