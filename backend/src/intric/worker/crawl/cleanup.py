from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Sequence, Set
from dataclasses import dataclass
from typing import assert_never

from intric.websites.domain.crawl_cleanup_policy import CleanupPolicy

CleanupDeleteCallback = Callable[[Sequence[str]], Awaitable[int]]


@dataclass(frozen=True, slots=True)
class CleanupResult:
    stale_titles: tuple[str, ...]
    deleted_count: int


async def cleanup_stale_blobs(
    *,
    existing_titles: Iterable[str],
    must_keep_titles: Set[str],
    failed_titles: Set[str],
    cleanup_policy: CleanupPolicy,
    delete_stale_titles: CleanupDeleteCallback,
) -> CleanupResult:
    """Compute stale titles and invoke the delete callback when policy allows."""

    match cleanup_policy:
        case CleanupPolicy.CLEANUP_ALLOWED:
            stale_titles = [
                title
                for title in existing_titles
                if title not in must_keep_titles and title not in failed_titles
            ]
        case CleanupPolicy.CLEANUP_SKIPPED_PARTIAL:
            stale_titles = []
        case CleanupPolicy.CLEANUP_NOT_REACHED | CleanupPolicy.CLEANUP_NOOP:
            raise RuntimeError(f"stale cleanup reached with {cleanup_policy.value}")
        case _:
            assert_never(cleanup_policy)

    if not stale_titles:
        return CleanupResult(stale_titles=(), deleted_count=0)

    stale_title_tuple = tuple(stale_titles)
    deleted_count = await delete_stale_titles(stale_title_tuple)
    return CleanupResult(
        stale_titles=stale_title_tuple,
        deleted_count=deleted_count,
    )
