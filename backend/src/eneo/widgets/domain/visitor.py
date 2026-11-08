# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from eneo.widgets.domain.widget import Widget


class WidgetVisitorContext(BaseModel):
    """Carried on the synthetic visitor ``UserInDB`` (``active_widget``).

    Mirrors ``active_api_key`` for service keys: the only access path into a
    space is the widget itself, and sessions are owned by widget + visitor.
    """

    model_config = ConfigDict(frozen=True)

    widget_id: UUID
    visitor_id: UUID
    tenant_id: UUID
    space_id: UUID
    target_id: UUID
    token_generation: int = Field(ge=0, strict=True)
    preview: bool = Field(default=False, strict=True)
    # Retention 0: conversation content must never be committed, so the
    # session service keeps placeholders inside the request transaction.
    never_persist: bool = False


@dataclass(frozen=True)
class VisitorClaims:
    widget_id: UUID
    tenant_id: UUID
    visitor_id: UUID
    generation: int
    issued_at: datetime
    expires_at: datetime
    jti: str
    # Minted for an editor's live preview: admits draft and paused widgets.
    preview: bool = False


@dataclass(frozen=True)
class WidgetPrincipal:
    """The authenticated party on the anonymous widget surface.

    Deliberately not a ``UserInDB``: nothing downstream may mistake a visitor
    for a user, and there is no users row to key ownership on.
    """

    widget: Widget
    visitor_id: UUID
    claims: VisitorClaims

    @property
    def tenant_id(self) -> UUID:
        return self.widget.tenant_id
