"""Scope claims of loopback MCP tokens.

Each internal server reads only its own claim, so an insights token cannot
double as a knowledge-search token for the same assistant and vice versa.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.authentication.auth_service import AuthService
from eneo.internal_mcp.foundation import assistant_id_from_token, verified_claims
from eneo.internal_mcp.insights import insight_target_from_token

pytestmark = pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning")


def _user():
    return SimpleNamespace(email="anna@kommun.se", username="anna")


def test_insight_target_claims_round_trip():
    target_id = uuid4()
    token = AuthService().create_scoped_mcp_token(
        _user(), insight_target=("group_chat", target_id)
    )

    assert insight_target_from_token(token) == ("group_chat", target_id)
    claims = verified_claims(token)
    assert claims["insight_target_type"] == "group_chat"
    assert claims["insight_target_id"] == str(target_id)
    assert "assistant_id" not in claims


def test_insights_token_is_not_an_assistant_scope():
    token = AuthService().create_scoped_mcp_token(
        _user(), insight_target=("assistant", uuid4())
    )

    with pytest.raises(ValueError):
        assistant_id_from_token(token)


def test_assistant_token_is_not_an_insights_scope():
    token = AuthService().create_scoped_mcp_token(_user(), assistant_id=uuid4())

    with pytest.raises(ValueError):
        insight_target_from_token(token)


def test_at_least_one_scope_is_required():
    with pytest.raises(ValueError):
        AuthService().create_scoped_mcp_token(_user())


def test_both_scopes_may_be_carried_together():
    assistant_id = uuid4()
    target_id = uuid4()
    token = AuthService().create_scoped_mcp_token(
        _user(), assistant_id=assistant_id, insight_target=("assistant", target_id)
    )

    assert assistant_id_from_token(token) == assistant_id
    assert insight_target_from_token(token) == ("assistant", target_id)
