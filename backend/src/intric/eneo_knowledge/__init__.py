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

from intric.eneo_knowledge.client import (
    CreatedCollection,
    EneoKnowledgeClient,
    EneoKnowledgeError,
    KnowledgeCollection,
    PairedMcpServer,
    UploadedFileInfo,
)
from intric.eneo_knowledge.feature_flag import is_enabled
from intric.eneo_knowledge.models import (
    KnowledgeSourceCreate,
    KnowledgeSourceCreateResponse,
    KnowledgeSourceFile,
    KnowledgeSourceSparse,
)
from intric.eneo_knowledge.router import router
from intric.eneo_knowledge.service import (
    KnowledgeSourceCreated,
    KnowledgeSourceRow,
    KnowledgeSourceService,
)
from intric.eneo_knowledge.table import KnowledgeSources

__all__ = [
    "CreatedCollection",
    "EneoKnowledgeClient",
    "EneoKnowledgeError",
    "KnowledgeCollection",
    "KnowledgeSourceCreate",
    "KnowledgeSourceCreateResponse",
    "KnowledgeSourceCreated",
    "KnowledgeSourceFile",
    "KnowledgeSourceRow",
    "KnowledgeSourceService",
    "KnowledgeSourceSparse",
    "KnowledgeSources",
    "PairedMcpServer",
    "UploadedFileInfo",
    "is_enabled",
    "router",
]
