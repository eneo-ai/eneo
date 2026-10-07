from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    cast,
)
from uuid import UUID

from eneo.flows.domain.rag_evidence import (
    RagEmbeddingModel,
    RagEmbeddingModelStatus,
    RagRetrievalRecord,
)
from eneo.flows.domain.rag_evidence_policy import FlowRagEvidencePolicy
from eneo.flows.domain.runtime import StepDiagnostic
from eneo.flows.flow_run_provenance import default_rag_tracking
from eneo.flows.runtime.protocols import RuntimeAssistantProtocol
from eneo.flows.runtime.rag_metadata import build_retrieved_knowledge_evidence
from eneo.info_blobs.info_blob import InfoBlobChunkInDBWithScore

if TYPE_CHECKING:
    from eneo.assistants.references import ReferencesService


@dataclass(frozen=True)
class RagRetrievalDeps:
    references_service: ReferencesService | None
    rag_retrieval_timeout_seconds: float
    evidence_policy: FlowRagEvidencePolicy
    logger: logging.Logger


def _embedding_model_evidence(
    datastore_result: object,
) -> tuple[RagEmbeddingModel | None, RagEmbeddingModelStatus]:
    """Read back the embedding model retrieval actually embedded the query with.

    The retrieval service owns which model a query runs against; Flows records
    what it reports rather than re-deriving it from the knowledge sources.
    """
    name = getattr(datastore_result, "embedding_model_name", None)
    if not isinstance(name, str) or not name.strip():
        return None, "not_reported"
    model_id = getattr(datastore_result, "embedding_model_id", None)
    return {
        "id": str(model_id) if model_id is not None else None,
        "name": name.strip(),
    }, "recorded"


async def retrieve_rag_chunks(
    *,
    assistant: RuntimeAssistantProtocol,
    question: str,
    run_id: UUID,
    step_order: int,
    deps: RagRetrievalDeps,
) -> tuple[list[InfoBlobChunkInDBWithScore], dict[str, Any], list[StepDiagnostic]]:
    info_blob_chunks: list[InfoBlobChunkInDBWithScore] = []
    rag_diagnostics: list[StepDiagnostic] = []
    rag_record = RagRetrievalRecord(
        timeout_seconds=int(deps.rag_retrieval_timeout_seconds),
        reference_metadata_status="skipped_unavailable",
        tracking=default_rag_tracking(),
    )
    if deps.references_service is None:
        rag_record.status = "skipped_no_service"
        return info_blob_chunks, rag_record.to_payload(), rag_diagnostics
    if not assistant.has_knowledge():
        rag_record.status = "skipped_no_knowledge"
        return info_blob_chunks, rag_record.to_payload(), rag_diagnostics
    if not question.strip():
        rag_record.status = "skipped_no_input"
        return info_blob_chunks, rag_record.to_payload(), rag_diagnostics

    rag_record.attempted = True
    retrieval_started = time.monotonic()
    try:
        datastore_result = await asyncio.wait_for(
            deps.references_service.get_references(
                question=question,
                collections=assistant.collections,
                websites=assistant.websites,
                integration_knowledge_list=assistant.integration_knowledge_list,
                version=1,
                include_info_blobs=False,
            ),
            timeout=deps.rag_retrieval_timeout_seconds,
        )
        info_blob_chunks = list(getattr(datastore_result, "chunks", []) or [])
        no_duplicate_chunks = list(
            getattr(datastore_result, "no_duplicate_chunks", info_blob_chunks) or []
        )
        source_ids = list(
            dict.fromkeys(
                str(getattr(chunk, "info_blob_id", ""))
                for chunk in info_blob_chunks
                if getattr(chunk, "info_blob_id", None) is not None
            )
        )
        source_metadata_by_id: dict[str, dict[str, Any]] | None = None
        metadata_loader = getattr(
            deps.references_service, "get_reference_metadata", None
        )
        if callable(metadata_loader):
            typed_metadata_loader = cast(
                Callable[..., Awaitable[dict[object, dict[str, Any]] | None]],
                metadata_loader,
            )
            metadata_ids = list(
                dict.fromkeys(
                    getattr(chunk, "info_blob_id")
                    for chunk in info_blob_chunks
                    if getattr(chunk, "info_blob_id", None) is not None
                )
            )
            if metadata_ids:
                try:
                    raw_metadata = await typed_metadata_loader(
                        info_blob_ids=metadata_ids
                    )
                except Exception as exc:
                    rag_record.reference_metadata_status = "error"
                    rag_record.reference_metadata_error_type = exc.__class__.__name__
                    deps.logger.warning(
                        "flow_executor.rag_reference_metadata_failed run_id=%s step_order=%d",
                        run_id,
                        step_order,
                        exc_info=True,
                    )
                else:
                    if isinstance(raw_metadata, dict):
                        source_metadata_by_id = {
                            str(key): value
                            for key, value in cast(
                                dict[object, Any], raw_metadata
                            ).items()
                            if isinstance(value, dict)
                        }
                    rag_record.reference_metadata_status = "success"
        evidence = build_retrieved_knowledge_evidence(
            info_blob_chunks,
            source_metadata_by_id=source_metadata_by_id,
            policy=deps.evidence_policy,
        )
        rag_record.status = "success" if info_blob_chunks else "no_chunks"
        rag_record.retrieval_duration_ms = int(
            (time.monotonic() - retrieval_started) * 1000
        )
        rag_record.chunks_retrieved = len(info_blob_chunks)
        rag_record.raw_chunks_count = len(info_blob_chunks)
        rag_record.deduped_chunks_count = len(no_duplicate_chunks)
        rag_record.unique_sources = len(source_ids)
        rag_record.source_ids = source_ids
        rag_record.source_ids_short = [source_id[:8] for source_id in source_ids]
        embedding_model, embedding_model_status = _embedding_model_evidence(
            datastore_result
        )
        rag_record.embedding_model = embedding_model
        rag_record.embedding_model_status = embedding_model_status
        rag_record.evidence = evidence
        if not info_blob_chunks:
            rag_diagnostics.append(
                StepDiagnostic(
                    code="rag_retrieval_no_chunks",
                    message=(
                        f"Step {step_order}: knowledge retrieval returned no chunks."
                    ),
                    severity="warning",
                )
            )
    except asyncio.TimeoutError:
        rag_record.status = "timeout"
        rag_record.error_code = "rag_retrieval_timeout"
        rag_record.retrieval_error_type = "TimeoutError"
        rag_record.retrieval_duration_ms = int(
            (time.monotonic() - retrieval_started) * 1000
        )
        rag_diagnostics.append(
            StepDiagnostic(
                code="rag_retrieval_timeout",
                message=f"RAG retrieval exceeded {deps.rag_retrieval_timeout_seconds}s timeout.",
            )
        )
        deps.logger.warning(
            "flow_executor.rag_timeout run_id=%s step_order=%d timeout=%s",
            run_id,
            step_order,
            deps.rag_retrieval_timeout_seconds,
        )
    except Exception as exc:
        rag_record.status = "error"
        rag_record.error_code = "rag_retrieval_failed"
        rag_record.retrieval_error_type = exc.__class__.__name__
        rag_record.retrieval_duration_ms = int(
            (time.monotonic() - retrieval_started) * 1000
        )
        rag_diagnostics.append(
            StepDiagnostic(
                code="rag_retrieval_failed",
                message="RAG retrieval failed.",
            )
        )
        deps.logger.warning(
            "flow_executor.rag_failed run_id=%s step_order=%d",
            run_id,
            step_order,
            exc_info=True,
        )
    return info_blob_chunks, rag_record.to_payload(), rag_diagnostics
