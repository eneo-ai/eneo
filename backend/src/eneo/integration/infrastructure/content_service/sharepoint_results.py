"""One sync pass's counts, bounded persisted summaries and failure outcomes.

No Graph, Redis or database I/O. Full and delta syncs, indexing and cleanup
use these same rules; the orchestrator decides when to persist their result.
"""

from typing import Literal

from eneo.integration.domain.skip_reasons import SkippedDetail, skipped_by_code
from eneo.integration.infrastructure.content_service.types import (
    ChangeKind,
    SyncMetadata,
    SyncStats,
)
from eneo.observability.error_text import user_visible_error

_MAX_SKIPPED_DETAILS = 50
_MAX_CHANGED_DETAILS = 50
BlobOutcome = Literal["added", "updated", "unchanged", "empty", "failed"]


class SyncItemsFailed(Exception):
    """A pass that reached its end but could not finish every item.

    Raised after the pass persisted what it could, so the ordinary failure path
    records it; the summary rides along so the failure record keeps the counts
    and the skipped details that name the files.
    """

    def __init__(
        self,
        summary: SyncStats,
        *,
        changes_detected: int | None = None,
        message: str | None = None,
    ):
        failed = summary.get("failed_items", 0)
        super().__init__(
            message
            or f"{failed} file{'s' if failed != 1 else ''} could not be processed; "
            f"the next sync retries {'them' if failed != 1 else 'it'}"
        )
        self.summary = summary
        self.changes_detected = changes_detected


class SyncAccessDenied(SyncItemsFailed):
    """Every download of the pass was refused (HTTP 403), and enough of them.

    A refusal among successes, or one of a handful, is about that file (a
    sensitivity label, a broken-inheritance folder): its indexed copy goes and
    the pass moves past it. When nothing of a meaningful number could be
    downloaded the problem is the identity (a conditional access policy, a
    changed Sites.Selected grant), so nothing is removed and the pass fails
    and keeps its token. See ``refused_access``.
    """

    def __init__(
        self, summary: SyncStats, *, forbidden: int, changes_detected: int | None = None
    ):
        super().__init__(
            summary,
            changes_detected=changes_detected,
            message=(
                f"SharePoint refused all {forbidden} "
                f"download{'s' if forbidden != 1 else ''} (HTTP 403); check the "
                "integration's access to this library, the next sync retries "
                f"{'them' if forbidden != 1 else 'it'}"
            ),
        )


class DeltaBaselineUnavailable(SyncItemsFailed):
    """A full sync finished without a delta token to continue from.

    Without one every change notification starts another full sync, so the
    pass is not a success: it is recorded as failed and the next sync is a
    full one that tries again.
    """

    def __init__(self, summary: SyncStats, *, detail: str | None) -> None:
        cause = f" ({detail})" if detail else ""
        super().__init__(
            summary,
            message=(
                f"SharePoint change tracking could not be started{cause}; the "
                "documents are imported and the next sync is a full one"
            ),
        )


def failure_summary(failure: Exception) -> SyncStats | None:
    return failure.summary if isinstance(failure, SyncItemsFailed) else None


def summary_counts(stats: SyncStats) -> dict[str, int | bool | str]:
    summary: dict[str, int | bool | str] = {
        "files_processed": stats.get("files_processed", 0),
        "files_deleted": stats.get("files_deleted", 0),
        "pages_processed": stats.get("pages_processed", 0),
        "folders_processed": stats.get("folders_processed", 0),
        "unchanged_items": stats.get("unchanged_items", 0),
        "skipped_items": stats.get("skipped_items", 0),
        "skipped_total": stats.get("skipped_total", stats.get("skipped_items", 0)),
        "skipped_truncated": stats.get("skipped_truncated", False),
    }
    if failed_items := stats.get("failed_items", 0):
        summary["failed_items"] = failed_items
    reconcile_warning = stats.get("reconcile_warning")
    if reconcile_warning:
        summary["reconcile_warning"] = reconcile_warning
    return summary


def record_change(stats: SyncStats, file: str, change: ChangeKind) -> None:
    total = stats.get("changed_total", 0) + 1
    stats["changed_total"] = total
    if total <= _MAX_CHANGED_DETAILS:
        stats.setdefault("changed_details", []).append({"file": file, "change": change})


def delta_worth_logging(summary: SyncStats) -> bool:
    """Delta runs are frequent; only keep the ones that changed something or warned."""
    return (
        summary.get("files_processed", 0) > 0
        or summary.get("files_deleted", 0) > 0
        or summary.get("skipped_items", 0) > 0
        or bool(summary.get("reconcile_warning"))
    )


def sync_metadata(
    stats: SyncStats | None = None,
    *,
    trigger: str,
    recovery: str | None = None,
    changes_detected: int | None = None,
) -> SyncMetadata:
    metadata: SyncMetadata = {"trigger": trigger}

    if stats is not None:
        metadata["files_processed"] = stats.get("files_processed", 0)
        metadata["files_deleted"] = stats.get("files_deleted", 0)
        metadata["out_of_scope_deleted"] = stats.get("out_of_scope_deleted", 0)
        metadata["pages_processed"] = stats.get("pages_processed", 0)
        metadata["folders_processed"] = stats.get("folders_processed", 0)
        metadata["unchanged_items"] = stats.get("unchanged_items", 0)
        metadata["skipped_items"] = stats.get("skipped_items", 0)
        metadata["skipped_total"] = stats.get(
            "skipped_total", stats.get("skipped_items", 0)
        )
        metadata["skipped_truncated"] = stats.get("skipped_truncated", False)
        metadata["skipped_details"] = stats.get("skipped_details", [])
        metadata["changed_total"] = stats.get("changed_total", 0)
        metadata["changed_truncated"] = stats.get("changed_truncated", False)
        metadata["changed_details"] = stats.get("changed_details", [])
        if failed_items := stats.get("failed_items", 0):
            metadata["failed_items"] = failed_items
        reconcile_warning = stats.get("reconcile_warning")
        if reconcile_warning:
            metadata["reconcile_warning"] = reconcile_warning
    if recovery:
        metadata["recovery"] = recovery
    if changes_detected is not None:
        metadata["changes_detected"] = changes_detected

    return metadata


def count_outcome(
    stats: SyncStats, outcome: BlobOutcome, item_name: str, *, page: bool = False
) -> None:
    if outcome == "added" or outcome == "updated":
        stats["pages_processed" if page else "files_processed"] += 1
        record_change(stats, item_name, outcome)
    elif outcome == "unchanged":
        stats["unchanged_items"] += 1
    elif outcome == "empty":
        count_skip(stats, skipped_by_code(item_name, "empty_content"))


def count_skip(stats: SyncStats, detail: SkippedDetail) -> None:
    stats["skipped_items"] += 1
    stats["skipped_details"].append(detail)


def count_failure(
    stats: SyncStats, detail: SkippedDetail, *, item_id: str | None = None
) -> None:
    """Count an item the pass could not finish; the pass must not move past it.

    ``item_id`` names the drive item a later pass can retry on its own.
    """
    stats["failed_items"] = stats.get("failed_items", 0) + 1
    stats["skipped_items"] += 1
    stats["skipped_details"].append({**detail, "retry": True})
    if item_id:
        stats.setdefault("failures_by_item", {}).setdefault(item_id, []).append(
            len(stats["skipped_details"]) - 1
        )


def failed_item_ids(stats: SyncStats) -> list[str]:
    return list(stats.get("failures_by_item", {}))


def unretryable_failures(stats: SyncStats) -> int:
    """Failures no item id names; only a full sync can make up for them."""
    named = sum(len(indexes) for indexes in stats.get("failures_by_item", {}).values())
    return stats.get("failed_items", 0) - named


def set_aside(stats: SyncStats, item_id: str, *, attempts: int) -> None:
    """Turn the item's failures into skips, so the pass may move past it."""
    details = stats["skipped_details"]
    for index in stats.get("failures_by_item", {}).pop(item_id, []):
        failure = details[index]
        details[index] = skipped_by_code(
            failure["file"], "set_aside", attempts=attempts, detail=failure["reason"]
        )
        stats["failed_items"] = stats.get("failed_items", 0) - 1


def initialize_stats() -> SyncStats:
    return {
        "files_processed": 0,
        "files_deleted": 0,
        "out_of_scope_deleted": 0,
        "folders_processed": 0,
        "pages_processed": 0,
        "unchanged_items": 0,
        "skipped_items": 0,
        "failed_items": 0,
        "skipped_details": [],
        "changed_details": [],
        "changed_total": 0,
    }


def count_download_attempt(stats: SyncStats) -> None:
    stats["download_attempts"] = stats.get("download_attempts", 0) + 1


def count_refused_download(stats: SyncStats, item_id: str, item_name: str = "") -> None:
    """A download refused with 403: about the file unless ``refused_access``."""
    stats["download_forbidden"] = stats.get("download_forbidden", 0) + 1
    stats.setdefault("refused_downloads", {})[item_id] = item_name or item_id


# Fewer refused downloads than this say nothing about the identity, even when
# nothing else could be downloaded: one restricted file must not hold a pass.
_MIN_REFUSALS_FOR_ACCESS_PROBLEM = 3


def refused_access(stats: SyncStats) -> int:
    """How many downloads were refused when that says the identity lost access, else 0.

    Every download of the pass refused, and at least
    ``_MIN_REFUSALS_FOR_ACCESS_PROBLEM`` of them.
    """
    attempts = stats.get("download_attempts", 0)
    if (
        attempts >= _MIN_REFUSALS_FOR_ACCESS_PROBLEM
        and stats.get("download_forbidden", 0) == attempts
    ):
        return attempts
    return 0


def summarize_pass(stats: SyncStats) -> tuple[SyncStats, int]:
    """The pass summary, and how many downloads were refused if ``refused_access``.

    Refusals were counted as file-level skips as they came; once the pass
    shows they are about the identity they become its failures.
    """
    forbidden = refused_access(stats)
    if forbidden:
        stats["failed_items"] = stats.get("failed_items", 0) + forbidden
    return build_summary_stats(stats), forbidden


def build_summary_stats(stats: SyncStats) -> SyncStats:
    """What the sync status and the sync log keep; its text is user-visible."""
    skipped_details = stats.get("skipped_details", [])
    all_changed_details = stats.get("changed_details", [])
    changed_details = all_changed_details[:_MAX_CHANGED_DETAILS]
    changed_total = stats.get("changed_total", len(all_changed_details))
    summary: SyncStats = {
        "files_processed": stats.get("files_processed", 0),
        "files_deleted": stats.get("files_deleted", 0),
        "out_of_scope_deleted": stats.get("out_of_scope_deleted", 0),
        "pages_processed": stats.get("pages_processed", 0),
        "folders_processed": stats.get("folders_processed", 0),
        "unchanged_items": stats.get("unchanged_items", 0),
        "skipped_items": stats.get("skipped_items", 0),
        "skipped_total": stats.get("skipped_items", 0),
        "skipped_truncated": len(skipped_details) > _MAX_SKIPPED_DETAILS,
        "skipped_details": [
            {**detail, "reason": user_visible_error(detail["reason"])}
            for detail in skipped_details[:_MAX_SKIPPED_DETAILS]
        ],
        "changed_total": changed_total,
        "changed_truncated": changed_total > len(changed_details),
        "changed_details": changed_details,
    }
    if failed_items := stats.get("failed_items", 0):
        summary["failed_items"] = failed_items
    reconcile_warning = stats.get("reconcile_warning")
    if reconcile_warning:
        summary["reconcile_warning"] = user_visible_error(reconcile_warning)
    return summary


def format_summary_for_job(summary: SyncStats) -> str:
    files = summary.get("files_processed", 0) or 0
    deleted = summary.get("files_deleted", 0) or 0
    pages = summary.get("pages_processed", 0) or 0
    folders = summary.get("folders_processed", 0) or 0
    unchanged = summary.get("unchanged_items", 0) or 0
    skipped = summary.get("skipped_items", 0) or 0

    processed_parts: list[str] = []
    if files:
        processed_parts.append(f"{files} file{'s' if files != 1 else ''}")
    if deleted:
        processed_parts.append(f"{deleted} deleted file{'s' if deleted != 1 else ''}")
    if pages:
        processed_parts.append(f"{pages} page{'s' if pages != 1 else ''}")
    if not processed_parts:
        processed_parts.append("0 files")

    extra_parts: list[str] = []
    if folders:
        extra_parts.append(f"{folders} folder{'s' if folders != 1 else ''} scanned")
    if unchanged:
        extra_parts.append(f"{unchanged} unchanged")
    if skipped:
        extra_parts.append(f"{skipped} item{'s' if skipped != 1 else ''} skipped")

    message = "Imported " + ", ".join(processed_parts)
    if extra_parts:
        message = f"{message} ({'; '.join(extra_parts)})"
    return message
