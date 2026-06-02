from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from intric.scim.constants import SCIM_FILTER_MAX_RESULTS


def clamp_count(count: int | None) -> int:
    """Clamp a SCIM ``count`` query parameter to the advertised page-size cap.

    ServiceProviderConfig advertises ``filter.maxResults = SCIM_FILTER_MAX_RESULTS``,
    so list endpoints must never return more than that in a single page — both a
    contract guarantee and protection against full-table dumps on large tenants.
    Per RFC 7644 §3.4.2.4 a negative ``count`` is interpreted as 0, and an
    omitted ``count`` falls back to the server's maximum page size rather than an
    unbounded query. Clients page through the rest via ``startIndex``.
    """
    if count is None:
        return SCIM_FILTER_MAX_RESULTS
    if count < 0:
        return 0
    return min(count, SCIM_FILTER_MAX_RESULTS)


_FILTER_RE = re.compile(
    r'(\w+(?:\.\w+)?)\s+(eq|ne|co|sw|ew|gt|lt|ge|le|pr)\s*(?:"([^"]*)")?',
    re.IGNORECASE,
)


@dataclass
class ScimFilter:
    attribute: str
    operator: str
    value: str | None = None

    @staticmethod
    def parse(filter_str: str) -> ScimFilter | None:
        m = _FILTER_RE.match(filter_str.strip())
        if not m:
            return None
        return ScimFilter(
            attribute=m.group(1),
            operator=m.group(2).lower(),
            value=m.group(3),
        )


@dataclass
class ScimSort:
    attribute: str
    order: str = "ascending"  # ascending | descending

    @staticmethod
    def parse(sort_by: str | None, sort_order: str | None) -> ScimSort | None:
        if not sort_by:
            return None
        return ScimSort(
            attribute=sort_by,
            order=(sort_order or "ascending").lower(),
        )


class ListResponse(BaseModel):
    schemas: list[str] = ["urn:ietf:params:scim:api:messages:2.0:ListResponse"]
    totalResults: int
    startIndex: int = 1
    itemsPerPage: int
    Resources: list[dict[str, Any]] = []
