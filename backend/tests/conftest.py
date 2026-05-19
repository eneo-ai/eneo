"""
Root-level conftest for all tests.

This provides a session-scoped event loop that works for both
integration tests (with session-scoped async fixtures) and
unit tests (with function-scoped tests).
"""

import os

# CRITICAL: Set crawler settings BEFORE importing pytest_plugins
# pytest_plugins imports modules that trigger get_settings() at module load time
# Settings validation requires TENANT_WORKER_SEMAPHORE_TTL_SECONDS > CRAWL_MAX_LENGTH
if not os.getenv("CRAWL_MAX_LENGTH"):
    os.environ["CRAWL_MAX_LENGTH"] = "1800"  # 30 minutes
if not os.getenv("TENANT_WORKER_SEMAPHORE_TTL_SECONDS"):
    os.environ["TENANT_WORKER_SEMAPHORE_TTL_SECONDS"] = "3600"  # 1 hour

import asyncio
from typing import TYPE_CHECKING

import pytest

from tests.warning_filters import IGNORED_WARNINGS

if TYPE_CHECKING:
    from _pytest.terminal import TerminalReporter

# Import shared fixture modules
# These fixtures are automatically discovered by pytest
# Organized to mirror the backend source structure (src/intric/*)
pytest_plugins = [
    "tests.integration.fixtures.completion_models",  # Completion model fixtures
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
