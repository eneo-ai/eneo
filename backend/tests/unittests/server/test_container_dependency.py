from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from dependency_injector import providers

from eneo.main.container.container import Container
from eneo.object_content.content import StorageKind
from eneo.object_content.deployment_policy import UploadAdmissionSnapshot
from eneo.server.dependencies import container as container_dependency


class _Session:
    def __init__(self, *, in_transaction: bool = False) -> None:
        self._in_transaction = in_transaction
        self.begin_calls = 0

    def in_transaction(self) -> bool:
        return self._in_transaction

    def begin(self) -> "_Transaction":
        self.begin_calls += 1
        return _Transaction(self)


class _Transaction:
    def __init__(self, session: _Session) -> None:
        self._session = session

    async def __aenter__(self) -> None:
        self._session._in_transaction = True

    async def __aexit__(self, *_args: object) -> None:
        self._session._in_transaction = False


async def test_inactive_user_setup_uses_non_ambient_authentication_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session()
    user = SimpleNamespace(is_active=False)
    authenticate = AsyncMock(return_value=user)
    container = SimpleNamespace(
        session=lambda: session,
        user_service=lambda: SimpleNamespace(authenticate=authenticate),
    )

    async def _setup_user(*, container: object, user: object) -> None:
        del container, user
        assert session.in_transaction()

    monkeypatch.setattr(container_dependency, "setup_user", _setup_user)
    monkeypatch.setattr(
        container_dependency,
        "override_user",
        lambda *, container, user: container,
    )

    dependency = container_dependency.get_container(
        with_user=True,
        with_transaction=False,
    )
    resolved = await dependency(
        request=SimpleNamespace(method="POST"),
        token="token",
        api_key="",
        container=container,
    )

    assert resolved is container
    assert session.begin_calls == 1
    authenticate.assert_awaited_once()


async def test_load_container_upload_admission_binds_one_immutable_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session(in_transaction=True)
    snapshot = UploadAdmissionSnapshot(
        policy_revision=8,
        session_storage_target=StorageKind.OBJECT_STORE,
        session_operator_ceiling_bytes=None,
        session_file_maximum_bytes=11,
        session_image_maximum_bytes=12,
        session_audio_maximum_bytes=13,
        knowledge_file_maximum_bytes=14,
        knowledge_audio_maximum_bytes=15,
    )
    loader = AsyncMock(return_value=snapshot)
    monkeypatch.setattr(
        container_dependency,
        "load_upload_admission_snapshot",
        loader,
    )
    monkeypatch.setattr(
        container_dependency,
        "object_content_runtime",
        SimpleNamespace(inline_maximum_bytes=99),
    )
    container = Container(session=providers.Object(session))

    resolved = await container_dependency.load_container_upload_admission(container)

    assert resolved is snapshot
    assert container.upload_admission() is snapshot
    loader.assert_awaited_once_with(session, inline_maximum_bytes=99)
