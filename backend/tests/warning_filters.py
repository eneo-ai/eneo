"""Structured pytest warning ignores with mandatory resolution paths.

Every entry in :data:`IGNORED_WARNINGS` must declare *why* we tolerate the
warning today and *how* it gets removed. The ``WarningFilter`` constructor
enforces this at import time — adding an ignore without a reason or
resolution will fail collection immediately.

The aim is to prevent ignore-list rot: each entry stays a TODO until
someone does the work or removes the entry.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WarningFilter:
    """A single ``warnings.filterwarnings`` entry with traceable rationale.

    Fields mirror the Python warning-filter tuple
    ``(action, message_regex, category, module_regex, lineno)``.
    """

    pattern: str
    """Regex matched against the warning message. Use ``".*"`` to match any."""

    category: str
    """Warning class name, e.g. ``"DeprecationWarning"``. Empty matches all."""

    reason: str
    """Why this warning is silenced today."""

    resolution: str
    """Concrete action that will let us delete this entry."""

    module: str = ""
    """Optional regex matched against the originating module."""

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError(
                f"WarningFilter(pattern={self.pattern!r}) is missing 'reason'. "
                "Every ignore must explain why it exists."
            )
        if not self.resolution.strip():
            raise ValueError(
                f"WarningFilter(pattern={self.pattern!r}) is missing 'resolution'. "
                "Every ignore must describe how it will be removed."
            )

    def to_filter_string(self) -> str:
        """Render as a pytest ``filterwarnings`` ini value.

        Format: ``ignore:<pattern>:<category>:<module>``. Trailing empty
        segments are stripped so pytest accepts the value.
        """
        parts = ["ignore", self.pattern, self.category, self.module]
        while parts and parts[-1] == "":
            parts.pop()
        return ":".join(parts)


IGNORED_WARNINGS: list[WarningFilter] = [
    WarningFilter(
        pattern="Please use `import python_multipart` instead.",
        category="PendingDeprecationWarning",
        reason=(
            "starlette still imports the legacy `multipart` package name during "
            "module import, before our code has a chance to suppress it."
        ),
        resolution=(
            "Bump starlette once it drops the multipart shim (or pin python-multipart "
            "to a version that re-exports under the new name) and remove this entry."
        ),
    ),
    WarningFilter(
        pattern=r"isSet\(\) is deprecated, use is_set\(\) instead",
        category="DeprecationWarning",
        reason=(
            "crochet calls threading.Event.isSet() on Python 3.12+; we transitively "
            "depend on it via the integration test stack."
        ),
        resolution=(
            "Upgrade crochet once upstream switches to is_set() (track "
            "https://github.com/itamarst/crochet/) or remove the crochet dependency."
        ),
    ),
    WarningFilter(
        pattern=r"coroutine 'AsyncMockMixin\._execute_mock_call' was never awaited",
        category="RuntimeWarning",
        reason=(
            "AsyncMock attribute access yields AsyncMock children, so chained sync "
            "lookups (mock.foo.bar()) produce coroutines that GC discards. A handful "
            "of legacy tests still trigger this on tear-down."
        ),
        resolution=(
            "Audit remaining AsyncMock fixtures and either pass spec= to constrain "
            "method types or override the offending attribute with a plain MagicMock. "
            "Once the suite no longer emits this, delete the entry."
        ),
    ),
    WarningFilter(
        pattern=".*",
        category="pytest.PytestUnraisableExceptionWarning",
        reason=(
            "httpx/redis/asyncpg clients sometimes get GC'd after the event loop "
            "closes, raising ResourceWarning inside __del__ which pytest re-raises."
        ),
        resolution=(
            "Audit fixtures that own async clients and ensure explicit aclose()/close() "
            "in teardown before the loop shuts down. Once teardown is deterministic, "
            "remove this entry along with the ResourceWarning one below."
        ),
    ),
    WarningFilter(
        pattern=".*",
        category="ResourceWarning",
        reason=(
            "Companion to the PytestUnraisableExceptionWarning entry — same root "
            "cause, surfaces as the inner ResourceWarning that __del__ emits."
        ),
        resolution=(
            "Same as the PytestUnraisableExceptionWarning entry above; delete both "
            "together once async client fixtures are fully deterministic."
        ),
    ),
    WarningFilter(
        pattern="Setting per-request cookies=.*",
        category="DeprecationWarning",
        module="httpx._client",
        reason=(
            "httpx >=0.28 deprecated per-request `cookies=`; a handful of "
            "integration tests in tests/integration/audit/ still use that pattern."
        ),
        resolution=(
            "Move cookies onto the AsyncClient fixture (client.cookies.update(...)) "
            "in tests/integration/audit/test_audit_*.py so requests inherit them, "
            "then delete this entry."
        ),
    ),
]
