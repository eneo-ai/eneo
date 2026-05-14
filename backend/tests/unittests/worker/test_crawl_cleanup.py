import ast
from collections.abc import Sequence
from pathlib import Path

import pytest

import intric.worker.crawl.cleanup as cleanup
from intric.websites.domain.crawl_cleanup_policy import CleanupPolicy
from intric.worker.crawl.cleanup import cleanup_stale_blobs


@pytest.mark.asyncio
async def test_cleanup_allowed_deletes_ordered_stale_titles_and_reports_them() -> None:
    deleted_title_batches: list[tuple[str, ...]] = []

    async def delete_stale_titles(titles: Sequence[str]) -> int:
        deleted_title_batches.append(tuple(titles))
        return len(titles)

    result = await cleanup_stale_blobs(
        existing_titles=["a", "b", "c", "d"],
        must_keep_titles={"b"},
        failed_titles={"d"},
        cleanup_policy=CleanupPolicy.CLEANUP_ALLOWED,
        delete_stale_titles=delete_stale_titles,
    )

    assert deleted_title_batches == [("a", "c")]
    assert result.stale_titles == deleted_title_batches[0]
    assert result.deleted_count == 2


@pytest.mark.asyncio
async def test_cleanup_allowed_with_no_stale_titles_does_not_call_deleter() -> None:
    async def delete_stale_titles(_titles: Sequence[str]) -> int:
        raise AssertionError("delete_stale_titles should not be called")

    result = await cleanup_stale_blobs(
        existing_titles=["a", "b"],
        must_keep_titles={"a"},
        failed_titles={"b"},
        cleanup_policy=CleanupPolicy.CLEANUP_ALLOWED,
        delete_stale_titles=delete_stale_titles,
    )

    assert result.stale_titles == ()
    assert result.deleted_count == 0


@pytest.mark.asyncio
async def test_partial_cleanup_policy_does_not_delete_missing_titles() -> None:
    async def delete_stale_titles(_titles: Sequence[str]) -> int:
        raise AssertionError("delete_stale_titles should not be called")

    result = await cleanup_stale_blobs(
        existing_titles=["source-retained", "not-seen-before-timeout"],
        must_keep_titles={"source-retained"},
        failed_titles=set(),
        cleanup_policy=CleanupPolicy.CLEANUP_SKIPPED_PARTIAL,
        delete_stale_titles=delete_stale_titles,
    )

    assert result.stale_titles == ()
    assert result.deleted_count == 0


@pytest.mark.parametrize(
    "cleanup_policy",
    [
        CleanupPolicy.CLEANUP_NOT_REACHED,
        CleanupPolicy.CLEANUP_NOOP,
    ],
)
@pytest.mark.asyncio
async def test_unreachable_cleanup_policies_raise_runtime_error(
    cleanup_policy: CleanupPolicy,
) -> None:
    async def delete_stale_titles(_titles: Sequence[str]) -> int:
        raise AssertionError("delete_stale_titles should not be called")

    with pytest.raises(RuntimeError, match="stale cleanup reached with"):
        await cleanup_stale_blobs(
            existing_titles=["deleted"],
            must_keep_titles=set(),
            failed_titles=set(),
            cleanup_policy=cleanup_policy,
            delete_stale_titles=delete_stale_titles,
        )


@pytest.mark.asyncio
async def test_delete_callback_exception_propagates() -> None:
    async def delete_stale_titles(_titles: Sequence[str]) -> int:
        raise ValueError("delete failed")

    with pytest.raises(ValueError, match="delete failed"):
        await cleanup_stale_blobs(
            existing_titles=["deleted"],
            must_keep_titles=set(),
            failed_titles=set(),
            cleanup_policy=CleanupPolicy.CLEANUP_ALLOWED,
            delete_stale_titles=delete_stale_titles,
        )


def test_cleanup_phase_has_no_runtime_or_infrastructure_imports() -> None:
    assert cleanup.__file__ is not None
    source = Path(cleanup.__file__).read_text()
    tree = ast.parse(source)
    forbidden_module_prefixes = (
        "arq",
        "dependency_injector",
        "intric.admin",
        "intric.crawler",
        "intric.main.container",
        "intric.sysadmin",
        "intric.worker.crawl.recovery",
        "intric.worker.crawl.terminal",
        "scrapy",
        "sqlalchemy",
    )
    forbidden_names = {
        "AsyncSession",
        "Container",
        "HeartbeatMonitor",
        "SessionHolder",
        "TerminalEvent",
        "execute_with_recovery",
        "providers",
    }
    imported_modules: set[str] = set()
    imported_names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)
                imported_names.add(alias.asname or alias.name.split(".")[-1])
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None:
                imported_modules.add(node.module)
            for alias in node.names:
                imported_names.add(alias.asname or alias.name)

    assert not any(
        module == prefix or module.startswith(f"{prefix}.")
        for module in imported_modules
        for prefix in forbidden_module_prefixes
    )
    assert not forbidden_names.intersection(imported_names)
