"""
Root-level conftest for all tests.

This provides a session-scoped event loop that works for both
integration tests (with session-scoped async fixtures) and
unit tests (with function-scoped tests).
"""
import asyncio

import pytest


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
