# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from eneo.widgets.domain.widget import (
    DEFAULT_AI_DISCLOSURE,
    Widget,
    WidgetLanguage,
    WidgetTexts,
    WidgetTheme,
    clean_text,
)

TEMPLATE_FIELDS = (
    "name",
    "description",
    "texts",
    "theme",
    "language",
    "is_default",
    "locked_groups",
)


class TemplateLockGroup(str, Enum):
    """The parts of a widget a template can govern.

    Groups, not fields: they match how the editor lays the settings out and
    keep the lock configuration small enough to reason about. Suggested
    questions are never templated; they depend on the assistant behind the
    widget.
    """

    APPEARANCE = "appearance"
    LANGUAGE = "language"
    # The AI disclosure under the title and the footer note with its link.
    LEGAL_TEXTS = "legal_texts"
    WORDING = "wording"


ALL_LOCK_GROUPS: tuple[TemplateLockGroup, ...] = tuple(TemplateLockGroup)
DEFAULT_LOCK_GROUPS: tuple[TemplateLockGroup, ...] = (
    TemplateLockGroup.APPEARANCE,
    TemplateLockGroup.LANGUAGE,
)

LOCK_GROUP_TEXT_FIELDS: dict[TemplateLockGroup, tuple[str, ...]] = {
    TemplateLockGroup.LEGAL_TEXTS: (
        "subtitle",
        "footer_text",
        "footer_link_url",
        "footer_link_label",
    ),
    TemplateLockGroup.WORDING: ("title", "welcome", "placeholder"),
}


def _as_texts(value: Any) -> WidgetTexts:
    return (
        value if isinstance(value, WidgetTexts) else WidgetTexts.model_validate(value)
    )


def _as_theme(value: Any) -> WidgetTheme:
    return (
        value if isinstance(value, WidgetTheme) else WidgetTheme.model_validate(value)
    )


class TemplateContent(BaseModel):
    """What a template governs on a widget, and the rules for governing it.

    Only the visitor-facing look and wording (texts, theme, language) are
    templated. Limits, privacy and protection stay per widget under the
    tenant policy, so a template can never loosen what the policy sets.

    The same content exists twice on a template: the draft admins edit and
    the published release followers are held to.
    """

    model_config = ConfigDict(validate_assignment=True)

    texts: WidgetTexts = Field(default_factory=WidgetTexts)
    theme: WidgetTheme = Field(default_factory=WidgetTheme)
    language: WidgetLanguage = WidgetLanguage.AUTO
    locked_groups: list[TemplateLockGroup] = Field(
        default_factory=list[TemplateLockGroup]
    )

    @field_validator("locked_groups")
    @classmethod
    def _locked_groups(cls, value: list[TemplateLockGroup]) -> list[TemplateLockGroup]:
        chosen = set(value)
        return [group for group in ALL_LOCK_GROUPS if group in chosen]

    def lock_violations(self) -> list[str]:
        """Why the locks cannot be enforced as configured.

        Checked once all changes are applied, so a save that unlocks the legal
        texts and clears the subtitle in the same request is accepted.
        """
        if (
            TemplateLockGroup.LEGAL_TEXTS in self.locked_groups
            and not self.texts.subtitle
        ):
            return ["subtitle_required_for_legal_texts_lock"]
        return []

    def is_locked(self, group: TemplateLockGroup) -> bool:
        return group in self.locked_groups

    def project_onto(self, widget: Widget, groups: Iterable[TemplateLockGroup]) -> bool:
        """Write the given groups' values onto the widget.

        Returns True when the widget changed. Suggested questions and
        everything outside the groups are left alone.
        """
        wanted = set(groups)
        changed = False
        if TemplateLockGroup.APPEARANCE in wanted and widget.theme != self.theme:
            widget.theme = self.theme.model_copy(deep=True)
            changed = True
        if TemplateLockGroup.LANGUAGE in wanted and widget.language != self.language:
            widget.language = self.language
            changed = True
        text_updates: dict[str, Any] = {}
        for group, fields in LOCK_GROUP_TEXT_FIELDS.items():
            if group not in wanted:
                continue
            for field in fields:
                value = getattr(self.texts, field)
                if getattr(widget.texts, field) != value:
                    text_updates[field] = value
        if text_updates:
            widget.texts = widget.texts.model_copy(update=text_updates)
            changed = True
        return changed

    def locked_changes(self, widget: Widget, changes: Mapping[str, Any]) -> list[str]:
        """Dotted names of locked fields an update would change on the widget.

        Unchanged locked values pass, so a client that sends a group whole
        (texts) can still edit the group's unlocked fields.
        """
        violations: list[str] = []
        if (
            self.is_locked(TemplateLockGroup.APPEARANCE)
            and "theme" in changes
            and _as_theme(changes["theme"]) != widget.theme
        ):
            violations.append("theme")
        if (
            self.is_locked(TemplateLockGroup.LANGUAGE)
            and "language" in changes
            and WidgetLanguage(changes["language"]) != widget.language
        ):
            violations.append("language")
        if "texts" in changes:
            new_texts = _as_texts(changes["texts"])
            for group, fields in LOCK_GROUP_TEXT_FIELDS.items():
                if not self.is_locked(group):
                    continue
                for field in fields:
                    if getattr(new_texts, field) != getattr(widget.texts, field):
                        violations.append(f"texts.{field}")
        return violations


class TemplateRelease(TemplateContent):
    """The published state of a template: what followers are linked to, kept
    in step with and locked by. Only publishing replaces it."""


class WidgetTemplate(TemplateContent):
    """House style admins maintain and widgets can follow.

    The template's own content fields are the draft: autosaved, previewed,
    never pushed. Publishing turns the draft into ``published``; that release
    is copied onto widgets when they are linked and its locked groups are
    written onto every follower with each later publication.
    """

    id: Optional[UUID] = None
    tenant_id: UUID
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    is_default: bool = False
    published: Optional[TemplateRelease] = None
    published_at: Optional[datetime] = None
    published_by_user_id: Optional[UUID] = None
    created_by_user_id: Optional[UUID] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        cleaned = clean_text(value)
        if not cleaned:
            raise ValueError("name must not be empty.")
        return cleaned

    @field_validator("description")
    @classmethod
    def _description(cls, value: str) -> str:
        return clean_text(value)

    @classmethod
    def create(
        cls,
        *,
        tenant_id: UUID,
        name: str,
        language: WidgetLanguage = WidgetLanguage.AUTO,
        created_by_user_id: Optional[UUID] = None,
    ) -> "WidgetTemplate":
        disclosure_lang = "en" if language == WidgetLanguage.EN else "sv"
        return cls(
            tenant_id=tenant_id,
            name=name,
            language=language,
            texts=WidgetTexts(subtitle=DEFAULT_AI_DISCLOSURE[disclosure_lang]),
            locked_groups=list(DEFAULT_LOCK_GROUPS),
            created_by_user_id=created_by_user_id,
        )

    def apply_update(self, changes: dict[str, Any]) -> None:
        for field, value in changes.items():
            if field not in TEMPLATE_FIELDS or value is None:
                continue
            setattr(self, field, value)

    def draft_release(self) -> TemplateRelease:
        """The draft as it would be published."""
        return TemplateRelease(
            texts=self.texts.model_copy(deep=True),
            theme=self.theme.model_copy(deep=True),
            language=self.language,
            locked_groups=list(self.locked_groups),
        )

    @property
    def has_unpublished_changes(self) -> bool:
        return self.published != self.draft_release()

    def publish(self, *, by: Optional[UUID], now: Optional[datetime] = None) -> None:
        self.published = self.draft_release()
        self.published_at = now or datetime.now(timezone.utc)
        self.published_by_user_id = by
