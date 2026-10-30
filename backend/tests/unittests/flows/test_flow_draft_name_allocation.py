from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.flows.application.flow_draft_materialization_executor import (
    _deduplicate_flow_name,
)


class _FlowService:
    def __init__(self, *names: str) -> None:
        self._names = names

    async def list_flows(self, **_: object) -> list[SimpleNamespace]:
        return [SimpleNamespace(name=name) for name in self._names]


def _allocate(taken: tuple[str, ...], desired: str) -> str:
    return asyncio.run(
        _deduplicate_flow_name(
            flow_service=_FlowService(*taken),  # pyright: ignore[reportArgumentType]
            space_id=uuid4(),
            desired_name=desired,
        )
    )


@pytest.mark.parametrize(
    ("taken", "desired", "allocated"),
    [
        ((), "Weekly report", "Weekly report"),
        (("Weekly report",), "Weekly report", "Weekly report (2)"),
        (("Weekly report", "Weekly report (2)"), "Weekly report", "Weekly report (3)"),
        # A desired name that already ends in a number counts from its family.
        (("Weekly report (2)",), "Weekly report (2)", "Weekly report (3)"),
        (
            ("Weekly report", "Weekly report (2)"),
            "Weekly report (2)",
            "Weekly report (3)",
        ),
    ],
)
def test_a_taken_name_gets_the_next_free_number_of_its_family(
    taken: tuple[str, ...], desired: str, allocated: str
) -> None:
    assert _allocate(taken, desired) == allocated
