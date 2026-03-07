from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from intric.flows.runtime.models import StepDiagnostic
from intric.flows.runtime.rag_metadata import build_rag_references


@dataclass(frozen=True)
class RagRetrievalDeps:
    references_service: Any | None
    rag_retrieval_timeout_seconds: float
    rag_max_reference_sources: int
    rag_max_chunks_per_source: int
    logger: Any


async def retrieve_rag_chunks(
    *,
    assistant: Any,
    question: str,
    run_id: UUID,
    step_order: int,
    deps: RagRetrievalDeps,
) -> tuple[list[Any], dict[str, Any], list[StepDiagnostic]]:
    info_blob_chunks: list[Any] = []
    rag_diagnostics: list[StepDiagnostic] = []
    rag_metadata: dict[str, Any] = {
        "attempted": False,
        "status": "skipped_no_service",
        "version": 1,
        "timeout_seconds": int(deps.rag_retrieval_timeout_seconds),
        "include_info_blobs": False,
        "chunks_retrieved": 0,
        "raw_chunks_count": 0,
        "deduped_chunks_count": 0,
        "unique_sources": 0,
        "source_ids": [],
        "source_ids_short": [],
        "error_code": None,
        "retrieval_duration_ms": None,
        "retrieval_error_type": None,
        "references": [],
        "references_truncated": False,
    }
    if deps.references_service is None:
        rag_metadata["status"] = "skipped_no_service"
        return info_blob_chunks, rag_metadata, rag_diagnostics
    if not assistant.has_knowledge():
        rag_metadata["status"] = "skipped_no_knowledge"
        return info_blob_chunks, rag_metadata, rag_diagnostics
    if not question.strip():
        rag_metadata["status"] = "skipped_no_input"
        return info_blob_chunks, rag_metadata, rag_diagnostics

    rag_metadata["attempted"] = True
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
        references, references_truncated = build_rag_references(
            info_blob_chunks,
            max_sources=deps.rag_max_reference_sources,
            max_chunks_per_source=deps.rag_max_chunks_per_source,
            snippet_chars=200,
        )
        rag_metadata["status"] = "success"
        rag_metadata["retrieval_duration_ms"] = int((time.monotonic() - retrieval_started) * 1000)
        rag_metadata["chunks_retrieved"] = len(info_blob_chunks)
        rag_metadata["raw_chunks_count"] = len(info_blob_chunks)
        rag_metadata["deduped_chunks_count"] = len(no_duplicate_chunks)
        rag_metadata["unique_sources"] = len(source_ids)
        rag_metadata["source_ids"] = source_ids
        rag_metadata["source_ids_short"] = [source_id[:8] for source_id in source_ids]
        rag_metadata["references"] = references
        rag_metadata["references_truncated"] = references_truncated
    except asyncio.TimeoutError:
        rag_metadata["status"] = "timeout"
        rag_metadata["error_code"] = "rag_retrieval_timeout"
        rag_metadata["retrieval_error_type"] = "TimeoutError"
        rag_metadata["retrieval_duration_ms"] = int((time.monotonic() - retrieval_started) * 1000)
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
        rag_metadata["status"] = "error"
        rag_metadata["error_code"] = "rag_retrieval_failed"
        rag_metadata["retrieval_error_type"] = exc.__class__.__name__
        rag_metadata["retrieval_duration_ms"] = int((time.monotonic() - retrieval_started) * 1000)
        rag_diagnostics.append(
            StepDiagnostic(
                code="rag_retrieval_failed",
                message="RAG retrieval failed; continuing without knowledge chunks.",
            )
        )
        deps.logger.warning(
            "flow_executor.rag_failed run_id=%s step_order=%d",
            run_id,
            step_order,
            exc_info=True,
        )
    return info_blob_chunks, rag_metadata, rag_diagnostics
