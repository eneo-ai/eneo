"""
Root-level conftest for all tests.

This provides a session-scoped event loop that works for both
integration tests (with session-scoped async fixtures) and
unit tests (with function-scoped tests).
"""

import os
import sys as _sys
import tempfile as _tempfile
from pathlib import Path as _Path

# The repo is bind-mounted into the devcontainer, so host and container share
# the in-tree __pycache__. Bytecode embeds the absolute source path at compile
# time: a .pyc compiled on the host still validates (same mtime/size) inside
# the container but carries /Users/... paths, which breaks inspect.getsource
# and traceback rendering for the source-inspecting contract tests. Keep this
# process's bytecode cache in a per-environment tmp dir instead of the mount.
_sys.pycache_prefix = str(_Path(_tempfile.gettempdir()) / "eneo-pyc")

# CRITICAL: Set crawler settings BEFORE importing pytest_plugins
# pytest_plugins imports modules that trigger get_settings() at module load time
# Settings validation requires TENANT_WORKER_SEMAPHORE_TTL_SECONDS > CRAWL_MAX_LENGTH
if not os.getenv("CRAWL_MAX_LENGTH"):
    os.environ["CRAWL_MAX_LENGTH"] = "1800"  # 30 minutes
if not os.getenv("TENANT_WORKER_SEMAPHORE_TTL_SECONDS"):
    os.environ["TENANT_WORKER_SEMAPHORE_TTL_SECONDS"] = "3600"  # 1 hour

import asyncio
import faulthandler
import sys
import threading
import warnings
from typing import TYPE_CHECKING

import pytest

from tests.warning_filters import IGNORED_WARNINGS

if TYPE_CHECKING:
    from _pytest.terminal import TerminalReporter


def _install_warning_ignores_eagerly() -> None:
    """Apply the structured ignores via warnings.filterwarnings() right now.

    pytest's own ``filterwarnings = error`` (from pytest.ini) is active during
    conftest import, which means any warning raised while importing the
    integration conftest below would crash collection before pytest_configure
    has a chance to register our ignores. Pushing the ignores onto the global
    warnings filter list here ensures they win the match for import-time
    warnings (e.g. starlette pulling in legacy `multipart`).

    pytest_configure also registers them with the pytest config so they show
    up in -W reports and the terminal summary stays consistent.
    """
    for entry in IGNORED_WARNINGS:
        category = _resolve_category(entry.category)
        warnings.filterwarnings(
            "ignore",
            message=entry.pattern,
            category=category,
            module=entry.module or "",
        )


def _resolve_category(name: str) -> type[Warning]:
    """Map a category string (e.g. ``"DeprecationWarning"``) to its class."""
    if not name:
        return Warning
    if "." in name:
        module_name, attr = name.rsplit(".", 1)
        import importlib

        module = importlib.import_module(module_name)
        return getattr(module, attr)
    return getattr(__builtins__, name, None) or globals().get(name) or Warning


_install_warning_ignores_eagerly()


def pytest_configure(config: pytest.Config) -> None:
    """Register structured warning ignores so they ride alongside pytest.ini.

    Each entry in IGNORED_WARNINGS is forced to declare a resolution path; this
    hook turns them into real ``filterwarnings`` lines for pytest.
    """
    for entry in IGNORED_WARNINGS:
        config.addinivalue_line("filterwarnings", entry.to_filter_string())


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(
    session: pytest.Session,  # noqa: ARG001  # required by pytest hook contract
    exitstatus: int,
) -> None:
    """Guarantee the process always terminates with a clear, bounded signal.

    The tests themselves complete in ~11s, but interpreter shutdown can
    intermittently hang while joining a non-daemon thread left running by the
    test stack (a Twisted reactor started via Scrapy/crochet, or a leaked
    async client). When that happens the process never exits, so CI and
    automated callers wait indefinitely with no result after the summary line
    has already printed.

    This arms a daemon watchdog: if shutdown overruns the budget it dumps every
    thread's traceback (to pinpoint the offending thread) and hard-exits while
    preserving the pass/fail status. On a clean shutdown the daemon is killed
    with the process and this is a no-op — zero impact on normal runs. Set
    PYTEST_SHUTDOWN_WATCHDOG_SECONDS=0 to disable.
    """
    try:
        budget = float(os.getenv("PYTEST_SHUTDOWN_WATCHDOG_SECONDS", "60"))
    except ValueError:
        budget = 60.0
    if budget <= 0:
        return

    status = int(exitstatus)

    def _watchdog() -> None:
        import time

        time.sleep(budget)
        sys.stderr.write(
            f"\n[pytest watchdog] interpreter shutdown exceeded {budget:.0f}s "
            "after the session finished — a non-daemon thread is blocking exit. "
            "Dumping thread tracebacks and forcing exit "
            f"(status={status}).\n"
        )
        sys.stderr.flush()
        faulthandler.dump_traceback(all_threads=True)
        sys.stderr.flush()
        os._exit(status)

    threading.Thread(
        target=_watchdog, name="pytest-shutdown-watchdog", daemon=True
    ).start()


def pytest_terminal_summary(
    terminalreporter: "TerminalReporter",
    exitstatus: int,  # noqa: ARG001  # required by pytest hook contract
    config: pytest.Config,  # noqa: ARG001
) -> None:
    """Print the active warning ignores at the end of every run.

    We want this tech debt visible on every test run so it doesn't quietly
    rot. Each entry carries the concrete action required to delete it.
    """
    if not IGNORED_WARNINGS:
        return

    terminalreporter.write_sep("=", f"warning ignores ({len(IGNORED_WARNINGS)})")
    terminalreporter.write_line(
        "These filters silence pytest warnings today. Each must declare a "
        "resolution path — work them down, don't grow the list."
    )
    terminalreporter.write_line("")
    for entry in IGNORED_WARNINGS:
        category = entry.category or "Warning"
        terminalreporter.write_line(f"  • [{category}] {entry.pattern}")
        terminalreporter.write_line(f"      why: {entry.reason}")
        terminalreporter.write_line(f"      fix: {entry.resolution}")
        terminalreporter.write_line("")


@pytest.fixture(scope="session")
def event_loop():
    """
    Create a session-scoped event loop for all tests.

    This is required to support:
    - Session-scoped async fixtures in integration tests
    - Function-scoped async tests in unit tests

    The event loop is shared across all tests and closed at the end
    of the test session.
    """
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()
