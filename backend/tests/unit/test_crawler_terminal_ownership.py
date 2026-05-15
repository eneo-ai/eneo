"""Regression guards for the crawler terminal ownership boundary.

Crawler terminal CrawlRun/Job state belongs on the `crawl_terminal.py`
`TerminalEvent` / `commit_terminal(...)` path, not in crawler entrypoints.
"""

from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = BACKEND_ROOT / "src" / "intric"

CRAWLER_SOURCE_ROOTS = (
    SRC_ROOT / "worker",
    SRC_ROOT / "crawler",
    SRC_ROOT / "websites",
)

TERMINAL_OWNER = SRC_ROOT / "websites" / "domain" / "crawl_terminal.py"
CRAWLER_ENTRYPOINTS = (
    SRC_ROOT / "worker" / "crawl_tasks.py",
    SRC_ROOT / "websites" / "domain" / "crawl_service.py",
)


def _python_files_under(paths: tuple[Path, ...]) -> list[Path]:
    return sorted(
        file_path
        for root in paths
        for file_path in root.rglob("*.py")
        if "__pycache__" not in file_path.parts
    )


def _relative(path: Path) -> str:
    return str(path.relative_to(BACKEND_ROOT))


def test_crawler_crawl_run_terminal_writes_stay_in_canonical_owner():
    offenders: list[str] = []
    for file_path in _python_files_under(CRAWLER_SOURCE_ROOTS):
        if file_path == TERMINAL_OWNER:
            continue

        source = file_path.read_text()
        if "update(CrawlRuns)" in source or "sa.update(CrawlRuns)" in source:
            offenders.append(_relative(file_path))

    if offenders:
        pytest.fail(
            "Crawler CrawlRun terminal writes must stay in "
            f"{_relative(TERMINAL_OWNER)}. Route new terminal state through "
            f"TerminalEvent / commit_terminal(...). Offenders: {offenders}"
        )


def test_crawler_entrypoints_do_not_bypass_terminal_commit_for_job_state():
    forbidden_patterns = (
        "job_service.fail_job",
        "update(Jobs)",
        "sa.update(Jobs)",
        'setattr(task_manager, "_job_already_handled"',
        "task_manager._job_already_handled",
    )
    offenders: list[str] = []

    for file_path in CRAWLER_ENTRYPOINTS:
        source = file_path.read_text()
        matched = [pattern for pattern in forbidden_patterns if pattern in source]
        if matched:
            offenders.append(f"{_relative(file_path)}: {', '.join(matched)}")

    if offenders:
        pytest.fail(
            "Crawler entrypoints must not bypass TerminalEvent / "
            f"commit_terminal(...). Offenders: {offenders}"
        )
