from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from eneo.server.dependencies import container as container_dependencies


class _AuthenticationTransaction:
    def __init__(self, transaction_state: dict[str, bool]) -> None:
        self._transaction_state = transaction_state

    async def __aenter__(self) -> None:
        assert self._transaction_state["active"] is False
        self._transaction_state["active"] = True

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        self._transaction_state["active"] = False


@pytest.mark.asyncio
async def test_explicit_user_setup_runs_inside_authentication_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transaction_state = {"active": False}
    session = MagicMock()
    session.in_transaction.side_effect = lambda: transaction_state["active"]
    session.begin.return_value = _AuthenticationTransaction(transaction_state)

    user = SimpleNamespace(is_active=False)
    container = MagicMock()
    container.session.return_value = session
    container.user_service.return_value.authenticate = AsyncMock(return_value=user)

    setup_user = AsyncMock()

    async def assert_setup_transaction(*, container: object, user: object) -> None:
        assert transaction_state["active"] is True

    setup_user.side_effect = assert_setup_transaction
    monkeypatch.setattr(container_dependencies, "setup_user", setup_user)
    override_user = MagicMock()
    monkeypatch.setattr(container_dependencies, "override_user", override_user)

    dependency = container_dependencies.get_container_for_explicit_transaction(
        with_user=True
    )
    result = await dependency(
        request=SimpleNamespace(method="GET"),
        token="test-token",
        api_key="",
        container=container,
    )

    assert result is container
    container.user_service.return_value.authenticate.assert_awaited_once()
    setup_user.assert_awaited_once_with(container=container, user=user)
    override_user.assert_called_once_with(container=container, user=user)
    assert transaction_state["active"] is False
