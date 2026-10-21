"""A long-running job acts as the user it was enqueued for, attributes included.

Upload and crawl jobs send outbound headers built from that user's provisioned
attributes, so the bootstrap must carry ``scim_extensions`` and ``external_id``
into the job's container, and a retried job must read them again.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.scim.constants import SCIM_ENTERPRISE_USER_URN
from eneo.users.user import UserInDB
from eneo.worker import worker as worker_module


class _AsyncContext:
    def __init__(self, value: Any = None) -> None:
        self.value = value

    async def __aenter__(self) -> Any:
        return self.value

    async def __aexit__(self, *args: object) -> None:
        return None


def _row(user: UserInDB, **changes: Any) -> SimpleNamespace:
    """An ORM-like row: validated from attributes, as the bootstrap does."""
    fields = {name: getattr(user, name) for name in UserInDB.model_fields}
    return SimpleNamespace(**{**fields, **changes})


def _serve_rows(monkeypatch: pytest.MonkeyPatch, rows: list[SimpleNamespace]) -> None:
    def session() -> _AsyncContext:
        result = MagicMock()
        result.scalar_one_or_none.return_value = rows.pop(0)
        db = MagicMock()
        db.begin.return_value = _AsyncContext()
        db.execute = AsyncMock(return_value=result)
        return _AsyncContext(db)

    monkeypatch.setattr(
        worker_module, "sessionmanager", SimpleNamespace(session=session)
    )


async def test_each_run_acts_as_the_enqueuing_user_with_fresh_attributes(
    monkeypatch: pytest.MonkeyPatch, user: UserInDB
):
    enterprise = {SCIM_ENTERPRISE_USER_URN: {"department": "Miljö"}}
    _serve_rows(
        monkeypatch,
        [
            _row(user, external_id="ext-1", scim_extensions=enterprise),
            # Re-provisioned before the retry: the attribute is gone.
            _row(user, external_id="ext-1", scim_extensions=None),
        ],
    )
    seen: list[tuple[Any, Any]] = []

    async def job(job_id: Any, params: Any, container: Any) -> None:
        seen.append((container.user(), container.create_embeddings_service().user))

    wrapper = worker_module.Worker().long_running_function()(job)
    params = SimpleNamespace(user_id=user.id)

    await wrapper({"job_id": str(uuid4())}, params)
    await wrapper({"job_id": str(uuid4())}, params)

    (first_user, first_embedder), (retry_user, retry_embedder) = seen
    assert first_user.id == user.id
    assert first_user.external_id == "ext-1"
    assert first_user.scim_extensions == enterprise
    # The service that builds the headers gets the same user.
    assert first_embedder is first_user
    assert retry_user.scim_extensions is None
    assert retry_embedder is retry_user
