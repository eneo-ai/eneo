"""Ladan external service integration.

Ladan is a separate Next.js service (Postgres + pgvector + S3 + Redis) that
owns the "Knowledge source" surface: collections, file ingestion, semantic
search via paired MCP servers. eneo holds a single operator admin bearer and
proxies user actions on the space-scoped self-service path; tenant + space
isolation is enforced inside eneo via the ``knowledge_sources`` ownership
table.

Everything in this package is gated by :func:`feature_flag.is_enabled`.
When the integration is disabled (its env vars are unset), the router is
not registered, the client provider returns ``None``, and the rest of eneo
continues to work without any code path needing to know about it.

Public surface:

- ``LadanClient`` — thin httpx wrapper for Ladan's admin API
- ``KnowledgeSourceService`` — orchestrates create/list/delete + file ops
- ``KnowledgeSources`` — SQLAlchemy table (ownership map)
- ``router`` — FastAPI APIRouter holding the integration's endpoints
- ``is_enabled()`` — feature-flag helper based on settings
"""

from typing import Any

from intric.ladan.client import (
    CreatedCollection,
    KnowledgeCollection,
    LadanClient,
    LadanError,
    PairedMcpServer,
)
from intric.ladan.feature_flag import is_enabled
from intric.ladan.models import (
    KnowledgeSourceCreate,
    KnowledgeSourceCreateResponse,
    KnowledgeSourceSparse,
)
from intric.ladan.service import (
    KnowledgeSourceCreated,
    KnowledgeSourceRow,
    KnowledgeSourceService,
)
from intric.ladan.table import KnowledgeSources


def __getattr__(name: str) -> Any:
    """Lazy-resolve ``router`` to avoid an import cycle through ``Container``.

    ``container.py`` imports this package early (line ~87) to get
    ``LadanClient`` — long before ``class Container`` is declared at the
    bottom of that module. Eager-importing ``router`` here would pull
    ``Container`` back into a half-initialised state. Deferring the import
    to first attribute access keeps ``server/routers.py`` working
    (``from intric import ladan; ladan.router``) while letting
    ``container.py`` finish defining ``Container`` first.
    """
    if name == "router":
        from intric.ladan.router import router as _router

        return _router
    raise AttributeError(f"module 'intric.ladan' has no attribute {name!r}")


# ``router`` is intentionally resolved via ``__getattr__`` above (lazy import
# to break the Container cycle) but pyright can't see it statically. Keeping
# it out of __all__ avoids the reportUnsupportedDunderAll false-positive;
# callers still get it via `from intric.ladan import router`.
__all__ = [
    "CreatedCollection",
    "KnowledgeCollection",
    "KnowledgeSourceCreate",
    "KnowledgeSourceCreateResponse",
    "KnowledgeSourceCreated",
    "KnowledgeSourceRow",
    "KnowledgeSourceService",
    "KnowledgeSourceSparse",
    "KnowledgeSources",
    "LadanClient",
    "LadanError",
    "PairedMcpServer",
    "is_enabled",
]
