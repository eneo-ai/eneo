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

import pytest

# Import shared fixture modules
# These fixtures are automatically discovered by pytest
# Organized to mirror the backend source structure (src/intric/*)
pytest_plugins = [
    "tests.integration.fixtures.completion_models",  # Completion model fixtures
    "tests.integration.fixtures.assistants",         # Assistant fixtures
    "tests.integration.fixtures.apps",               # App fixtures
    "tests.integration.fixtures.services",           # Service fixtures
    "tests.integration.fixtures.spaces",             # Space fixtures
    "tests.integration.fixtures.organization_knowledge",  # Organization knowledge fixtures
]


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