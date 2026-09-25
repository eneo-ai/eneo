# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


import re
import secrets
from collections.abc import Callable
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from urllib.parse import urlparse
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from eneo.allowed_origins.origin_matching import normalize_origin_pattern
from eneo.main.exceptions import BadRequestException
from eneo.widgets.domain.exceptions import WidgetActivationRequestMissingError

PUBLIC_ID_PREFIX = "wgt_"
_PUBLIC_ID_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_PUBLIC_ID_LENGTH = 22
PUBLIC_ID_RE = re.compile(r"^wgt_[0-9A-Za-z]{22}$")
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

MAX_ALLOWED_ORIGINS = 20
MAX_SUGGESTED_QUESTIONS = 4
MAX_SUGGESTED_QUESTION_LENGTH = 160
# The daily usage counters are int4 columns.
MAX_DAILY_TOKEN_BUDGET = 2_000_000_000

# AI Act article 50: visitors must be told they are talking to an AI system.
# The text is editable per widget but never empty on an active widget.
DEFAULT_AI_DISCLOSURE = {
    "sv": (
        "Du chattar med en AI-assistent. Svaren kan innehålla fel – "
        "kontrollera viktig information."
    ),
    "en": (
        "You are chatting with an AI assistant. Answers may contain errors – "
        "verify important information."
    ),
}

# Changing any of these invalidates outstanding visitor tokens.
TOKEN_GENERATION_FIELDS = frozenset(
    {"allowed_origins", "limits", "privacy", "bot_protection"}
)

# A pending activation request and the last send-back. The request commands
# write only these; activate and archive clear them.
ACTIVATION_REVIEW_FIELDS = frozenset(
    {
        "activation_requested_at",
        "activation_requested_by_user_id",
        "activation_declined_at",
        "activation_declined_by_user_id",
        "activation_decline_reason",
    }
)

# The columns pause and archive write. They never touch configuration, so
# they bypass the revision check: a kill switch must not lose to an autosave.
LIFECYCLE_FIELDS = (
    frozenset({"status", "paused_at", "token_generation"}) | ACTIVATION_REVIEW_FIELDS
)


# What each configuration blocker is about: the widget cannot serve while the
# setting is empty.
_SERVING_REQUIREMENTS: dict[str, Callable[["Widget"], Any]] = {
    "allowed_origins_empty": lambda widget: widget.allowed_origins,
    "subtitle_empty": lambda widget: widget.texts.subtitle,
}


def generate_public_id() -> str:
    body = "".join(
        secrets.choice(_PUBLIC_ID_ALPHABET) for _ in range(_PUBLIC_ID_LENGTH)
    )
    return f"{PUBLIC_ID_PREFIX}{body}"


def is_public_id(value: str) -> bool:
    return bool(PUBLIC_ID_RE.match(value))


class WidgetStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class WidgetTargetType(str, Enum):
    ASSISTANT = "assistant"


class WidgetLanguage(str, Enum):
    SV = "sv"
    EN = "en"
    AUTO = "auto"


class WidgetColorScheme(str, Enum):
    AUTO = "auto"
    LIGHT = "light"
    DARK = "dark"


class WidgetPosition(str, Enum):
    BOTTOM_RIGHT = "bottom-right"
    BOTTOM_LEFT = "bottom-left"


class WidgetLauncher(str, Enum):
    BUBBLE = "bubble"
    BAR = "bar"
    NONE = "none"


class BotProtection(str, Enum):
    ALTCHA = "altcha"
    NONE = "none"


def clean_text(value: str) -> str:
    """Collapse whitespace; the normalisation every visitor-facing text gets."""
    return " ".join(value.split())


def validation_messages(exc: ValidationError) -> str:
    """Pydantic errors as one readable line for a 400 response."""
    return "; ".join(str(e.get("msg", e)) for e in exc.errors())


_clean = clean_text


class WidgetTexts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", max_length=80)
    welcome: str = Field(default="", max_length=500)
    placeholder: str = Field(default="", max_length=120)
    suggested_questions: list[str] = Field(
        default_factory=list, max_length=MAX_SUGGESTED_QUESTIONS
    )
    # Line under the title in the panel header. Defaults to an AI disclosure,
    # which is what the EU AI Act transparency duty expects it to say.
    subtitle: str = Field(default=DEFAULT_AI_DISCLOSURE["sv"], max_length=300)
    # Free footer note under the composer, e.g. a data-handling reminder or a
    # "powered by" line, with an optional link.
    footer_text: str = Field(default="", max_length=300)
    footer_link_url: Optional[str] = Field(default=None, max_length=500)
    footer_link_label: str = Field(default="", max_length=80)

    @field_validator(
        "title",
        "welcome",
        "placeholder",
        "subtitle",
        "footer_text",
        "footer_link_label",
    )
    @classmethod
    def _strip(cls, value: str) -> str:
        return _clean(value)

    @field_validator("suggested_questions")
    @classmethod
    def _questions(cls, value: list[str]) -> list[str]:
        cleaned = [_clean(q) for q in value]
        if any(not q for q in cleaned):
            raise ValueError("Suggested questions must not be empty.")
        if any(len(q) > MAX_SUGGESTED_QUESTION_LENGTH for q in cleaned):
            raise ValueError(
                f"Suggested questions must be at most {MAX_SUGGESTED_QUESTION_LENGTH} characters."
            )
        # The embed page keys the chips by their text; a repeated question
        # would take the whole panel down for every visitor.
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("Suggested questions must be unique.")
        return cleaned

    @field_validator("footer_link_url")
    @classmethod
    def _footer_link_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("footer_link_url must be an http(s) URL.")
        return value


class WidgetTheme(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_color: str = "#1F4E79"
    color_scheme: WidgetColorScheme = WidgetColorScheme.AUTO
    position: WidgetPosition = WidgetPosition.BOTTOM_RIGHT
    launcher: WidgetLauncher = WidgetLauncher.BUBBLE
    radius: int = Field(default=12, ge=0, le=24)
    # Panel header background; None keeps the neutral surface. Text colour on
    # it is picked automatically for contrast.
    header_color: Optional[str] = None
    # Optional colours for dark mode; None means the light-mode colour is
    # used in both modes.
    primary_color_dark: Optional[str] = None
    header_color_dark: Optional[str] = None
    # Logo shown in the panel header, hosted by the organisation.
    logo_url: Optional[str] = Field(default=None, max_length=500)
    # Kept for stored rows from the first schema; never populated.
    logo_file_id: Optional[UUID] = None

    @field_validator("primary_color")
    @classmethod
    def _hex(cls, value: str) -> str:
        value = value.strip()
        if not _HEX_COLOR_RE.match(value):
            raise ValueError("primary_color must be a #RRGGBB hex colour.")
        return value.upper()

    @field_validator("header_color", "primary_color_dark", "header_color_dark")
    @classmethod
    def _optional_hex(cls, value: Optional[str], info: ValidationInfo) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if not _HEX_COLOR_RE.match(value):
            raise ValueError(f"{info.field_name} must be a #RRGGBB hex colour.")
        return value.upper()

    @field_validator("logo_url")
    @classmethod
    def _logo_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("logo_url must be an http(s) URL.")
        return value


class WidgetLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages_per_visitor_10min: int = Field(default=10, ge=1, le=100)
    messages_per_ip_hour: int = Field(default=60, ge=1, le=1000)
    daily_token_budget: int = Field(
        default=500_000, ge=1_000, le=MAX_DAILY_TOKEN_BUDGET
    )
    max_question_chars: int = Field(default=2_000, ge=100, le=8_000)
    max_session_turns: int = Field(default=30, ge=1, le=100)


class WidgetPrivacy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # 0 means "never persist": answers stream, nothing is stored, no follow-ups.
    retention_days: int = Field(default=30, ge=0, le=3650)
    store_feedback_text: bool = False

    @property
    def never_persists(self) -> bool:
        return self.retention_days == 0


def normalize_allowed_origins(origins: list[str]) -> list[str]:
    seen: list[str] = []
    for origin in origins:
        normalized = normalize_origin_pattern(origin)
        if normalized not in seen:
            seen.append(normalized)
    if len(seen) > MAX_ALLOWED_ORIGINS:
        raise ValueError(
            f"At most {MAX_ALLOWED_ORIGINS} allowed origins are supported."
        )
    return seen


def frame_ancestor_sources(origins: list[str]) -> list[str]:
    """Allowed-origin patterns as CSP ``frame-ancestors`` host sources.

    Normalised origins are already ``scheme://host[:port]`` with optional
    ``*.`` host and ``*`` port wildcards, which CSP host-source syntax accepts
    verbatim; a bare host pattern gets no scheme so both http and https match.
    """
    return list(origins)


class Widget(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    id: Optional[UUID] = None
    public_id: str
    tenant_id: UUID
    space_id: UUID
    target_type: WidgetTargetType = WidgetTargetType.ASSISTANT
    target_id: UUID
    status: WidgetStatus = WidgetStatus.DRAFT
    token_generation: int = 0
    revision: int = Field(default=0, ge=0)
    name: str = Field(min_length=1, max_length=100)
    texts: WidgetTexts = Field(default_factory=WidgetTexts)
    theme: WidgetTheme = Field(default_factory=WidgetTheme)
    limits: WidgetLimits = Field(default_factory=WidgetLimits)
    privacy: WidgetPrivacy = Field(default_factory=WidgetPrivacy)
    language: WidgetLanguage = WidgetLanguage.AUTO
    allowed_origins: list[str] = Field(default_factory=list)
    bot_protection: BotProtection = BotProtection.ALTCHA
    # Visitors see numbered citations and a source list unless turned off.
    show_sources: bool = True
    # Tools always run; this only decides whether visitors see which tools
    # and MCP servers the answer used.
    show_tool_activity: bool = True
    # The template this widget follows; None for a stand-alone widget. Only
    # the link/detach commands change it, never a plain update.
    template_id: Optional[UUID] = None
    created_by_user_id: Optional[UUID] = None
    activated_by_user_id: Optional[UUID] = None
    activated_at: Optional[datetime] = None
    paused_at: Optional[datetime] = None
    activation_requested_at: Optional[datetime] = None
    activation_requested_by_user_id: Optional[UUID] = None
    activation_declined_at: Optional[datetime] = None
    activation_declined_by_user_id: Optional[UUID] = None
    activation_decline_reason: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    _serving_view: bool = PrivateAttr(default=False)

    @property
    def is_serving_view(self) -> bool:
        return self._serving_view

    def serving_copy(self, update: dict[str, Any]) -> "Widget":
        """A copy for the visitor surface (WidgetPolicy.serving); the
        repository refuses to write it back."""
        served = self.model_copy(update=update, deep=True)
        served._serving_view = True
        return served

    @field_validator("public_id")
    @classmethod
    def _public_id(cls, value: str) -> str:
        if not is_public_id(value):
            raise ValueError("Malformed widget public id.")
        return value

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        cleaned = _clean(value)
        if not cleaned:
            raise ValueError("name must not be empty.")
        return cleaned

    @field_validator("allowed_origins")
    @classmethod
    def _origins(cls, value: list[str]) -> list[str]:
        return normalize_allowed_origins(value)

    @model_validator(mode="after")
    def _status_consistency(self) -> "Widget":
        if self.status == WidgetStatus.ACTIVE and self.activated_at is None:
            raise ValueError("An active widget must record activated_at.")
        if self.activation_requested_at is not None:
            if self.status not in (WidgetStatus.DRAFT, WidgetStatus.PAUSED):
                raise ValueError("Only a draft or paused widget can await activation.")
            if self.activation_declined_at is not None:
                raise ValueError(
                    "A widget cannot await activation and be sent back at once."
                )
        return self

    @classmethod
    def create(
        cls,
        *,
        tenant_id: UUID,
        space_id: UUID,
        target_id: UUID,
        name: str,
        language: WidgetLanguage = WidgetLanguage.AUTO,
        created_by_user_id: Optional[UUID] = None,
        target_type: WidgetTargetType = WidgetTargetType.ASSISTANT,
    ) -> "Widget":
        disclosure_lang = "en" if language == WidgetLanguage.EN else "sv"
        return cls(
            public_id=generate_public_id(),
            tenant_id=tenant_id,
            space_id=space_id,
            target_type=target_type,
            target_id=target_id,
            name=name,
            language=language,
            texts=WidgetTexts(subtitle=DEFAULT_AI_DISCLOSURE[disclosure_lang]),
            created_by_user_id=created_by_user_id,
        )

    @property
    def is_serving(self) -> bool:
        return self.status == WidgetStatus.ACTIVE

    def activation_blockers(self, *, target_published: bool) -> list[str]:
        """Reasons this widget cannot serve visitors. Empty means activatable."""
        blockers: list[str] = []
        if self.status == WidgetStatus.ARCHIVED:
            blockers.append("archived")
        blockers.extend(self.configuration_blockers())
        if not target_published:
            blockers.append("target_not_published")
        return blockers

    def configuration_blockers(self) -> list[str]:
        """The activation blockers that are the widget's own settings."""
        return [
            code for code, setting in _SERVING_REQUIREMENTS.items() if not setting(self)
        ]

    def blockers_introduced_since(self, before: "Widget") -> list[str]:
        """Configuration blockers on settings that changed since ``before``.

        A serving widget must never be edited into a state it could not be
        activated in. One left standing on a setting the edit did not touch
        does not block the edit.
        """
        return [
            code
            for code in self.configuration_blockers()
            if _SERVING_REQUIREMENTS[code](self) != _SERVING_REQUIREMENTS[code](before)
        ]

    def request_activation(self, *, by: UUID, now: Optional[datetime] = None) -> bool:
        """Ask an administrator to activate the widget. Returns False when a
        request is already pending, so a repeated click changes nothing."""
        if self.status not in (WidgetStatus.DRAFT, WidgetStatus.PAUSED):
            raise BadRequestException(
                f"Cannot request activation of a widget in status"
                f" '{self.status.value}'."
            )
        if self.activation_requested_at is not None:
            return False
        # The send-back goes first: the validator rejects both at once.
        self._clear_activation_decline()
        self.activation_requested_by_user_id = by
        self.activation_requested_at = now or datetime.now(timezone.utc)
        return True

    def withdraw_activation_request(self) -> bool:
        """Returns False when no request is pending."""
        if self.activation_requested_at is None:
            return False
        self.activation_requested_at = None
        self.activation_requested_by_user_id = None
        return True

    def decline_activation_request(
        self, *, by: UUID, reason: str, now: Optional[datetime] = None
    ) -> None:
        """Send a pending request back to the space with a reason."""
        if self.activation_requested_at is None:
            raise WidgetActivationRequestMissingError()
        self.activation_requested_at = None
        self.activation_requested_by_user_id = None
        self.activation_decline_reason = reason
        self.activation_declined_by_user_id = by
        self.activation_declined_at = now or datetime.now(timezone.utc)

    def _clear_activation_decline(self) -> None:
        self.activation_declined_at = None
        self.activation_declined_by_user_id = None
        self.activation_decline_reason = None

    def _clear_activation_review(self) -> None:
        self.activation_requested_at = None
        self.activation_requested_by_user_id = None
        self._clear_activation_decline()

    def activate(self, *, by: UUID, now: Optional[datetime] = None) -> None:
        if self.status not in (WidgetStatus.DRAFT, WidgetStatus.PAUSED):
            raise BadRequestException(
                f"Cannot activate a widget in status '{self.status.value}'."
            )
        # Before the status: validate_assignment rejects an active widget
        # that still awaits activation.
        self._clear_activation_review()
        self.activated_at = now or datetime.now(timezone.utc)
        self.activated_by_user_id = by
        self.paused_at = None
        self.status = WidgetStatus.ACTIVE

    def pause(self, *, now: Optional[datetime] = None) -> None:
        if self.status != WidgetStatus.ACTIVE:
            raise BadRequestException(
                f"Cannot pause a widget in status '{self.status.value}'."
            )
        self.status = WidgetStatus.PAUSED
        self.paused_at = now or datetime.now(timezone.utc)
        self.token_generation += 1

    def archive(self) -> None:
        if self.status == WidgetStatus.ARCHIVED:
            raise BadRequestException("Widget is already archived.")
        self._clear_activation_review()
        self.status = WidgetStatus.ARCHIVED
        self.token_generation += 1

    def apply_update(self, changes: dict[str, Any]) -> bool:
        """Apply admin-editable fields. Returns True when the token generation
        was bumped because a visitor-facing policy field changed."""
        if self.status == WidgetStatus.ARCHIVED:
            raise BadRequestException("Archived widgets cannot be edited.")
        editable = {
            "name",
            "texts",
            "theme",
            "limits",
            "privacy",
            "language",
            "allowed_origins",
            "bot_protection",
            "show_sources",
            "show_tool_activity",
        }
        unknown = set(changes) - editable
        if unknown:
            raise BadRequestException(
                f"Fields cannot be updated: {', '.join(sorted(unknown))}."
            )
        bumped = False
        for field, value in changes.items():
            before = getattr(self, field)
            try:
                setattr(self, field, value)
            except ValidationError as exc:
                raise BadRequestException(
                    f"Invalid {field}: {validation_messages(exc)}"
                ) from exc
            if field in TOKEN_GENERATION_FIELDS and getattr(self, field) != before:
                bumped = True
        if bumped:
            self.token_generation += 1
        return bumped
