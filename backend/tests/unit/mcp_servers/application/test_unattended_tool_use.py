"""Every level of the chain can refuse an unattended tool call, in order."""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest

from eneo.mcp_servers.application.unattended_tool_use import (
    UnattendedToolFacts,
    UnattendedToolRefusal,
    unattended_tool_refusal,
)
from eneo.mcp_servers.domain.entities.mcp_server import (
    BUNDLED_AUTH_TYPE,
    INTERNAL_AUTH_TYPE,
    MCPServer,
    MCPServerTool,
)
from eneo.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)

R = UnattendedToolRefusal


def _level(security_level: int) -> SecurityClassification:
    return SecurityClassification(
        id=uuid4(),
        tenant_id=uuid4(),
        name=f"klass {security_level}",
        security_level=security_level,
        security_enabled=True,
    )


def _facts(
    *,
    server: dict[str, object] | None = None,
    tool: dict[str, object] | None = None,
    missing: str | None = None,
    **levels: object,
) -> UnattendedToolFacts:
    """An approved, switched-on tool of a general server its space activated,
    with the named facts changed."""
    the_server = MCPServer(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Cases",
        http_url="https://cases.example.org/mcp",
        is_enabled=True,
    )
    the_tool = MCPServerTool(
        id=uuid4(),
        mcp_server_id=the_server.id,
        name="lookup_case",
        is_enabled_by_default=True,
    )
    for entity, changes in ((the_server, server), (the_tool, tool)):
        for name, value in (changes or {}).items():
            setattr(entity, name, value)
    allowed = UnattendedToolFacts(
        server=None if missing == "server" else the_server,
        tool=None if missing == "tool" else the_tool,
        tenant_setting=None,
        space_is_personal=False,
        server_in_space=True,
        space_override=None,
        space_security_classification=None,
    )
    return replace(allowed, **levels)


# Each row is the allowed case with the named facts changed. A row with one
# change names the call that goes out if that level is not asked; a row with
# two names the order: the author is sent to whoever can change the FIRST one.
@pytest.mark.parametrize(
    ("facts", "refusal"),
    [
        # Kills "refuse everything", which every other row would pass.
        pytest.param(_facts(), None, id="allowed"),
        pytest.param(
            _facts(
                server={"security_classification": _level(2)},
                space_security_classification=_level(2),
            ),
            None,
            id="allowed-same-classification",
        ),
        # A tool that is off by default and that its space turned on.
        pytest.param(
            _facts(tool={"is_enabled_by_default": False}, space_override=True),
            None,
            id="allowed-space-turned-it-on",
        ),
        pytest.param(
            _facts(server={"is_enabled": False}), R.SERVER_DISABLED, id="server-off"
        ),
        pytest.param(
            _facts(server={"purpose": "web_search"}),
            R.SERVER_NOT_GENERAL,
            id="capability-provider",
        ),
        pytest.param(
            _facts(server={"http_auth_type": INTERNAL_AUTH_TYPE}),
            R.SERVER_NOT_GENERAL,
            id="eneo-own-server",
        ),
        pytest.param(
            _facts(server={"forward_identity": True}),
            R.SERVER_FORWARDS_IDENTITY,
            id="forwards-identity",
        ),
        # Kills the decision that lets a tool step send the server's
        # credential over plain http; the address rule itself has its own test.
        pytest.param(
            _facts(
                server={
                    "http_url": "http://cases.example.org/mcp",
                    "http_auth_type": "bearer",
                }
            ),
            R.SERVER_CREDENTIAL_NEEDS_HTTPS,
            id="credential-over-http",
        ),
        # Kills the decision that re-implements the transport rule instead of
        # calling credential_transport_violation: the shared rule lets plain
        # http through to a loopback host, and a user name and password in the
        # address are a credential whatever the auth type.
        pytest.param(
            _facts(
                server={
                    "http_url": "http://localhost:9000/mcp",
                    "http_auth_type": "bearer",
                }
            ),
            None,
            id="credential-over-http-to-loopback",
        ),
        pytest.param(
            _facts(
                server={
                    "http_url": "http://u:p@cases.example.org/mcp",
                    "http_auth_type": "none",
                }
            ),
            R.SERVER_CREDENTIAL_NEEDS_HTTPS,
            id="credential-in-the-address",
        ),
        # A bundled server gets the runtime token at the deployment's plain
        # http runtime URL: kills a decision that counts that token as an
        # admin-supplied credential and asks the address before the kind.
        pytest.param(
            _facts(
                server={
                    "http_auth_type": BUNDLED_AUTH_TYPE,
                    "purpose": "compute",
                    "http_url": "http://tool-runtime:8080/mcp/compute",
                }
            ),
            R.SERVER_NOT_GENERAL,
            id="bundled-over-http",
        ),
        # The grant of one server must not carry a tool of another.
        pytest.param(
            _facts(tool={"mcp_server_id": uuid4()}),
            R.TOOL_NOT_FOUND,
            id="tool-of-another-server",
        ),
        pytest.param(
            _facts(tool={"removed_from_remote": True}),
            R.TOOL_REMOVED_AT_SERVER,
            id="removed-at-server",
        ),
        pytest.param(
            _facts(tool={"requires_approval": True}),
            R.TOOL_WAITING_FOR_REVIEW,
            id="waiting-for-review",
        ),
        pytest.param(
            _facts(tenant_setting=False, space_override=True),
            R.TOOL_SWITCHED_OFF,
            id="off-for-all",
        ),
        pytest.param(
            _facts(tool={"is_enabled_by_default": False}),
            R.TOOL_SWITCHED_OFF,
            id="off-by-default",
        ),
        pytest.param(
            _facts(space_is_personal=True), R.SPACE_IS_PERSONAL, id="personal"
        ),
        pytest.param(
            _facts(server_in_space=False), R.SERVER_NOT_IN_SPACE, id="not-in-space"
        ),
        pytest.param(
            _facts(space_override=False),
            R.TOOL_SWITCHED_OFF_IN_SPACE,
            id="off-in-space",
        ),
        pytest.param(
            _facts(
                server={"security_classification": _level(2)},
                space_security_classification=_level(3),
            ),
            R.SERVER_BELOW_SPACE_CLASSIFICATION,
            id="below-space-classification",
        ),
        pytest.param(
            _facts(space_security_classification=_level(1)),
            R.SERVER_BELOW_SPACE_CLASSIFICATION,
            id="unclassified-server-classified-space",
        ),
        # Order.
        pytest.param(
            _facts(server={"is_enabled": False}, server_in_space=False),
            R.SERVER_DISABLED,
            id="order-server-before-space",
        ),
        # Kills the https check moved before the identity check: the author
        # would be told to ask for an https address on a server that is
        # refused whatever its address.
        pytest.param(
            _facts(
                server={
                    "http_url": "http://cases.example.org/mcp",
                    "http_auth_type": "bearer",
                    "forward_identity": True,
                }
            ),
            R.SERVER_FORWARDS_IDENTITY,
            id="order-identity-before-https",
        ),
        pytest.param(
            _facts(tool={"requires_approval": True}, space_override=False),
            R.TOOL_WAITING_FOR_REVIEW,
            id="order-review-before-space-switch",
        ),
        pytest.param(
            _facts(tenant_setting=False, server_in_space=False),
            R.TOOL_SWITCHED_OFF,
            id="order-instance-switch-before-space",
        ),
        # Kills the address asked before the server's kind: no administrator
        # change of the address lets a capability provider into a flow.
        pytest.param(
            _facts(
                server={
                    "purpose": "web_search",
                    "http_url": "http://search.example.org/mcp",
                    "http_auth_type": "bearer",
                }
            ),
            R.SERVER_NOT_GENERAL,
            id="order-kind-before-address",
        ),
        # Kills the address asked after the tool's levels: the author would
        # wait for a review that does not let the call out.
        pytest.param(
            _facts(
                server={
                    "http_url": "http://cases.example.org/mcp",
                    "http_auth_type": "api_key_header",
                },
                tool={"requires_approval": True},
            ),
            R.SERVER_CREDENTIAL_NEEDS_HTTPS,
            id="order-server-address-before-the-review",
        ),
        # A personal space is the answer whatever the levels have stored: an
        # author told "waits for review" asks an administrator who cannot help.
        pytest.param(
            _facts(tool={"requires_approval": True}, space_is_personal=True),
            R.SPACE_IS_PERSONAL,
            id="order-personal-before-the-review",
        ),
        pytest.param(
            _facts(missing="server", space_is_personal=True),
            R.SPACE_IS_PERSONAL,
            id="order-personal-before-a-deleted-server",
        ),
        pytest.param(
            _facts(
                tool={"removed_from_remote": True, "requires_approval": True},
            ),
            R.TOOL_REMOVED_AT_SERVER,
            id="order-removed-before-review",
        ),
    ],
)
def test_the_first_level_that_refuses_is_the_answer(
    facts: UnattendedToolFacts, refusal: UnattendedToolRefusal | None
) -> None:
    assert unattended_tool_refusal(facts) is refusal


@pytest.mark.parametrize(
    ("missing", "refusal"),
    [("server", R.SERVER_NOT_FOUND), ("tool", R.TOOL_NOT_FOUND)],
)
def test_a_deleted_server_or_tool_is_a_refusal_not_a_crash(
    missing: str, refusal: UnattendedToolRefusal
) -> None:
    # Kills the mutant that reads a deleted server or tool: a stored flow
    # still names it, and the run has to refuse with a reason.
    assert unattended_tool_refusal(_facts(missing=missing)) is refusal
