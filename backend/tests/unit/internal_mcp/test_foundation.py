from uuid import uuid4

from mcp.server.fastmcp import FastMCP

from eneo.internal_mcp.foundation import build_ephemeral_server


async def test_ephemeral_loopback_server_is_marked_internal():
    """The loopback factory is the only place that sets ``is_internal``: it is
    what distinguishes Eneo's own tools from an external server that happens
    to carry the same name."""
    server = await build_ephemeral_server(
        FastMCP("knowledge"),
        name="knowledge",
        description="Loopback",
        token="token",
        tenant_id=uuid4(),
    )

    assert server.is_internal is True
    assert server.name == "knowledge"


class TestDigestClaims:
    """The effective model and effort travel on the scoped token so a
    loopback tool that calls a model cannot fall back to stale settings."""

    def test_claims_round_trip_through_the_scoped_token(self):
        from eneo.authentication.auth_service import AuthService
        from eneo.internal_mcp.foundation import digest_claims_from_token
        from tests.fixtures import TEST_USER

        model_id, reader_id = uuid4(), uuid4()
        token = AuthService().create_scoped_mcp_token(
            TEST_USER,
            assistant_id=uuid4(),
            completion_model_id=model_id,
            reasoning_effort="medium",
            reasoning_enforced=True,
            reader_model_id=reader_id,
            reader_reason="inherited",
        )

        claims = digest_claims_from_token(token)

        assert claims.completion_model_id == model_id
        assert claims.reasoning_effort == "medium"
        assert claims.reasoning_enforced is True
        assert claims.reader_model_id == reader_id
        assert claims.reader_reason == "inherited"

    def test_tokens_without_the_claims_resolve_to_nothing(self):
        from eneo.authentication.auth_service import AuthService
        from eneo.internal_mcp.foundation import digest_claims_from_token
        from tests.fixtures import TEST_USER

        token = AuthService().create_scoped_mcp_token(TEST_USER, assistant_id=uuid4())

        claims = digest_claims_from_token(token)

        assert claims.completion_model_id is None
        assert claims.reasoning_effort is None
        assert claims.reasoning_enforced is False
        assert claims.reader_model_id is None
        assert claims.reader_reason is None
