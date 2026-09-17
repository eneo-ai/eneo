# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from eneo.widgets.domain.widget import (
    DEFAULT_AI_DISCLOSURE,
    WidgetLanguage,
    WidgetTexts,
    WidgetTheme,
    clean_text,
)

TEMPLATE_FIELDS = ("name", "description", "texts", "theme", "language", "is_default")


class WidgetTemplate(BaseModel):
    """House style admins maintain and editors copy onto new widgets.

    Only the visitor-facing look and wording (texts, theme, language) are
    templated. Limits, privacy and protection stay per widget under the
    tenant policy, so a template can never loosen what the policy sets.
    """

    model_config = ConfigDict(validate_assignment=True)

    id: Optional[UUID] = None
    tenant_id: UUID
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    texts: WidgetTexts = Field(default_factory=WidgetTexts)
    theme: WidgetTheme = Field(default_factory=WidgetTheme)
    language: WidgetLanguage = WidgetLanguage.AUTO
    is_default: bool = False
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
            texts=WidgetTexts(ai_disclosure=DEFAULT_AI_DISCLOSURE[disclosure_lang]),
            created_by_user_id=created_by_user_id,
        )

    def apply_update(self, changes: dict[str, Any]) -> None:
        for field, value in changes.items():
            if field not in TEMPLATE_FIELDS or value is None:
                continue
            setattr(self, field, value)
