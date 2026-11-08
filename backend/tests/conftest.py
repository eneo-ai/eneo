"""
Root-level conftest for all tests.

This provides a session-scoped event loop that works for both
integration tests (with session-scoped async fixtures) and
unit tests (with function-scoped tests).
"""

import os

# Set the shorter test crawl limit before imports that initialize settings.
if not os.getenv("CRAWL_MAX_LENGTH"):
    os.environ["CRAWL_MAX_LENGTH"] = "1800"  # 30 minutes

import asyncio
import contextlib
import faulthandler
import gc
import sys
import threading
import traceback
import types
import warnings
from collections.abc import Generator, Iterator
from typing import TYPE_CHECKING

import pytest

from tests.warning_filters import IGNORED_WARNINGS

try:
    from _pytest.faulthandler import fault_handler_stderr_fd_key
except ImportError:
    # Private pytest API: if it moves, only the asyncio watchdog switches off.
    fault_handler_stderr_fd_key = None

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


# Import shared fixture modules
# These fixtures are automatically discovered by pytest
# Organized to mirror the backend source structure (src/eneo/*)
pytest_plugins = [
    "tests.integration.fixtures.completion_models",  # Completion model fixtures
    "tests.integration.fixtures.transcription_models",  # Transcription model fixtures
    "tests.integration.fixtures.image_models",  # Image model fixtures
    "tests.integration.fixtures.rerank_models",  # Rerank model fixtures
    "tests.integration.fixtures.assistants",  # Assistant fixtures
    "tests.integration.fixtures.apps",  # App fixtures
    "tests.integration.fixtures.services",  # Service fixtures
    "tests.integration.fixtures.spaces",  # Space fixtures
    "tests.integration.fixtures.organization_knowledge",  # Organization knowledge fixtures
    "tests.integration.fixtures.integrations",  # Integration fixtures (SharePoint, etc.)
]


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
    intermittently hang while joining a non-daemon thread left running by a
    leaked async client. When that happens the process never exits, so CI and
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


# pytest's faulthandler plugin dumps on the same fd at faulthandler_timeout;
# starting later keeps the two dumps from interleaving.
_ASYNCIO_DUMP_DELAY_SECONDS = 1.0


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item: pytest.Item) -> Generator[None, object, object]:
    """Show where a test that outlives faulthandler_timeout is awaiting.

    faulthandler_timeout dumps every thread, which pinpoints a hung sync test.
    A hung async test shows only the event loop blocked in ``select``: neither
    the test nor the await it is stuck on. Shortly after that dump, this writes
    the nodeid and the await chain of every pending task on each running event
    loop to the same fd, which xdist workers share with the CI log.

    No-op when faulthandler_timeout is unset, the faulthandler plugin is off
    or pytest no longer exposes its fd key, and silent for a test that ends in
    time. faulthandler_exit_on_timeout ends the process before it fires.
    """
    config = item.config
    if (
        fault_handler_stderr_fd_key is None
        or fault_handler_stderr_fd_key not in config.stash
    ):
        return (yield)
    timeout = float(config.getini("faulthandler_timeout") or 0)
    if timeout <= 0:
        return (yield)

    timer = threading.Timer(
        timeout + _ASYNCIO_DUMP_DELAY_SECONDS,
        _dump_asyncio_tasks,
        args=(item.nodeid, timeout, config.stash[fault_handler_stderr_fd_key]),
    )
    timer.daemon = True
    timer.start()
    try:
        return (yield)
    finally:
        timer.cancel()


def _dump_asyncio_tasks(nodeid: str, timeout: float, fd: int) -> None:
    """Write the await chain of each pending task on every running event loop.

    Runs on the timer thread while the loop's thread is blocked, so it only
    reads coroutine and frame state. It must not raise: pytest would report a
    thread exception as a warning, which pytest.ini turns into a test error.
    """
    out = [f"\n[pytest asyncio watchdog] {nodeid} exceeded {timeout:g}s\n"]
    try:
        names = {thread.ident: thread.name for thread in threading.enumerate()}
        loops = 0
        for thread_id, frame in sys._current_frames().items():
            loop = _running_loop(frame)
            if loop is None:
                continue
            loops += 1
            tasks = asyncio.all_tasks(loop)
            thread_name = names.get(thread_id, thread_id)
            out.append(
                f"{len(tasks)} pending task(s) on the event loop in thread "
                f"{thread_name}:\n"
            )
            for task in tasks:
                out.append(f"Task {task.get_name()!r} (innermost await last):\n")
                chain = _await_chain(task.get_coro())
                out.extend(traceback.StackSummary.extract(chain).format())
        if not loops:
            out.append("No asyncio event loop is running.\n")
    except Exception as exc:
        out.append(f"Task dump failed: {exc!r}\n")
    with contextlib.suppress(OSError):
        os.write(fd, "".join(out).encode(errors="backslashreplace"))


def _running_loop(frame: types.FrameType | None) -> asyncio.AbstractEventLoop | None:
    """Return the event loop whose run_forever() is on this thread's stack."""
    while frame is not None:
        if frame.f_code.co_name == "run_forever":
            loop = frame.f_locals.get("self")
            if isinstance(loop, asyncio.AbstractEventLoop):
                return loop
        frame = frame.f_back
    return None


def _await_chain(awaitable: object) -> Iterator[tuple[types.FrameType, int]]:
    """Yield each frame from a task's coroutine down to the await it blocks on.

    Task.get_stack() stops at the outermost coroutine. The anext() wrappers that
    async generator fixtures and asynccontextmanager await have no frame, so
    the chain continues into the async generator they reference.
    """
    while awaitable is not None:
        frame = getattr(awaitable, "cr_frame", None) or getattr(
            awaitable, "ag_frame", None
        )
        if frame is None:
            awaitable = next(
                (
                    ref
                    for ref in gc.get_referents(awaitable)
                    if isinstance(ref, types.AsyncGeneratorType)
                ),
                None,
            )
            continue
        yield frame, frame.f_lineno
        awaitable = getattr(awaitable, "cr_await", None) or getattr(
            awaitable, "ag_await", None
        )


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


def pytest_collection_modifyitems(config, items):
    """Auto-skip tests with opt-in markers unless explicitly requested via -m."""
    OPT_IN_MARKERS = {"api_key_matrix"}

    # Check if any opt-in marker was explicitly requested via -m
    marker_expr = config.getoption("-m", default="")
    requested = {m for m in OPT_IN_MARKERS if m in marker_expr}

    skip_markers = OPT_IN_MARKERS - requested
    for item in items:
        for marker_name in skip_markers:
            if marker_name in item.keywords:
                item.add_marker(
                    pytest.mark.skip(
                        reason=f"'{marker_name}' tests require explicit -m {marker_name}"
                    )
                )


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
