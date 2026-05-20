"""eneo-knowledge external service integration.

eneo-knowledge is a separate Next.js service (Postgres + pgvector + S3 + Redis)
that owns the "Knowledge source" surface: collections, file ingestion, semantic
search via paired MCP servers. eneo holds a single operator admin bearer and
proxies user actions on the space-scoped self-service path; tenant + space
isolation is enforced inside eneo via the ``knowledge_sources`` ownership
table.

Everything in this package is gated by :func:`feature_flag.is_enabled`.
When the integration is disabled (its env vars are unset), the router is
not registered, the client provider returns ``None``, and the rest of eneo
continues to work without any code path needing to know about it.

Public surface:

- ``EneoKnowledgeClient`` — thin httpx wrapper for eneo-knowledge's admin API
- ``KnowledgeSourceService`` — orchestrates create/list/delete + file ops
- ``KnowledgeSources`` — SQLAlchemy table (ownership map)
- ``router`` — FastAPI APIRouter holding the integration's endpoints
- ``is_enabled()`` — feature-flag helper based on settings
"""

from typing import Any

from intric.eneo_knowledge.client import (
    CreatedCollection,
    EneoKnowledgeClient,
    EneoKnowledgeError,
    KnowledgeCollection,
    PairedMcpServer,
)
from intric.eneo_knowledge.feature_flag import is_enabled
from intric.eneo_knowledge.models import (
    KnowledgeSourceCreate,
    KnowledgeSourceCreateResponse,
    KnowledgeSourceSparse,
)
from intric.eneo_knowledge.service import (
    KnowledgeSourceCreated,
    KnowledgeSourceRow,
    KnowledgeSourceService,
)
from intric.eneo_knowledge.table import KnowledgeSources


def __getattr__(name: str) -> Any:
    """Lazy-resolve ``router`` to avoid an import cycle through ``Container``.

    ``container.py`` imports this package early (line ~87) to get
    ``EneoKnowledgeClient`` — long before ``class Container`` is declared
    at the bottom of that module. Eager-importing ``router`` here would
    pull ``Container`` back into a half-initialised state. Deferring the
    import to first attribute access keeps ``server/routers.py`` working
    (``from intric import eneo_knowledge; eneo_knowledge.router``) while
    letting ``container.py`` finish defining ``Container`` first.
    """
    if name == "router":
        from intric.eneo_knowledge.router import router as _router

        return _router
    raise AttributeError(f"module 'intric.eneo_knowledge' has no attribute {name!r}")


# ``router`` is intentionally resolved via ``__getattr__`` above (lazy import
# to break the Container cycle) but pyright can't see it statically. Keeping
# it out of __all__ avoids the reportUnsupportedDunderAll false-positive;
# callers still get it via `from intric.eneo_knowledge import router`.
__all__ = [
    "CreatedCollection",
    "EneoKnowledgeClient",
    "EneoKnowledgeError",
    "KnowledgeCollection",
    "KnowledgeSourceCreate",
    "KnowledgeSourceCreateResponse",
    "KnowledgeSourceCreated",
    "KnowledgeSourceRow",
    "KnowledgeSourceService",
    "KnowledgeSourceSparse",
    "KnowledgeSources",
    "PairedMcpServer",
    "is_enabled",
]
