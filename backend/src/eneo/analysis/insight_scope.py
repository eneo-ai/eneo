"""Value types shared by the insights repository, tools and service."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, NamedTuple
from uuid import UUID

InsightTargetKind = Literal["assistant", "group_chat"]


class InsightScope(NamedTuple):
    """What one insights conversation may look at."""

    kind: InsightTargetKind
    target_id: UUID
    tenant_id: UUID


class InsightWindow(NamedTuple):
    """Half-open ``[start, end)`` window of aware datetimes plus display zone."""

    start: datetime
    end: datetime
    timezone: str
