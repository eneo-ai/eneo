from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from eneo.authentication.auth_dependencies import require_session_auth


async def test_require_session_auth_returns_structured_api_key_denial():
    request = MagicMock()
    request.state.api_key = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        await require_session_auth(MagicMock(), request)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == {
        "code": "session_auth_required",
        "message": "This endpoint requires a session token.",
    }
