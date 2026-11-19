"""Value types shared by the insights repository, tools and service."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, NamedTuple
from uuid import UUID

InsightTargetKind = Literal["assistant", "group_chat"]
KnowledgeSourceKind = Literal["collection", "website", "integration_knowledge"]
# Why an answer counts as a knowledge miss: the knowledge search reported no
# results, the answer cited no passage, or its best passage scored weakly.
MissReason = Literal["no_results", "uncited", "weak_score"]
FindingKind = Literal[
    "knowledge_missed",
    "unanswered",
    "rephrasing",
    "knowledge_unused",
    "negative_ratings",
    "tool_failures",
]
# The findings whose cases can be listed one by one.
FindingCaseKind = Literal["knowledge_missed", "unanswered", "rephrasing"]


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
