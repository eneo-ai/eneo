"""How a run history is searched and ordered: metadata only, never run content."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Literal

FlowRunListSort = Literal["created_at", "started_at", "status", "duration"]
FlowRunListOrder = Literal["asc", "desc"]

FLOW_RUN_LIST_SEARCH_MAX_CHARS = 200


@dataclass(frozen=True, slots=True)
class FlowRunListing:
    """A run list's search and order.

    ``search`` matches the run label and the name of whoever started the run
    (a user's username or email, a service key's name), case-insensitively
    and as a substring. It never reaches accepted input, output or evidence.
    ``sort`` orders by when the run was created (the default), when it
    started (its creation time while it has not), its status in the status
    capability table's ``filter_order``, or how long it took (runs that have
    not finished last). Ties fall back to the newest run first, so paging
    stays stable.
    """

    search: str | None = None
    sort: FlowRunListSort = "created_at"
    order: FlowRunListOrder = "desc"

    @classmethod
    def of(
        cls,
        *,
        search: str | None = None,
        sort: FlowRunListSort = "created_at",
        order: FlowRunListOrder = "desc",
    ) -> "FlowRunListing":
        """The listing for a request: labels are stored NFC, so the search
        is too, and a blank search searches nothing."""
        cleaned = unicodedata.normalize("NFC", search).strip() if search else ""
        return cls(search=cleaned or None, sort=sort, order=order)
