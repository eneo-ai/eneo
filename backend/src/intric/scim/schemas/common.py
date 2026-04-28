from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

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
