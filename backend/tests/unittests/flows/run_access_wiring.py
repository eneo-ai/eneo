"""The flow gate's run access policy, for router tests whose container is a
MagicMock."""

from __future__ import annotations

from unittest.mock import MagicMock

from eneo.flows.application.flow_run_access_policy import FlowRunAccessPolicy


def wire_run_access_policy(container: MagicMock) -> None:
    """Resolve ``container.flow_run_access_policy()`` to a real policy over the
    container's mocks, so the gate decides as it does in a request.

    Each resolution builds a new policy from the mocks as they are then: a test
    may set them up after wiring, and each route it calls on one container
    reads as its own request."""

    container.flow_run_access_policy.side_effect = lambda: FlowRunAccessPolicy(
        user=container.user(),
        flow_repo=container.flow_repo(),
        flow_run_repo=container.flow_run_repo(),
        space_service=container.space_service(),
        actor_manager=container.actor_manager(),
    )
