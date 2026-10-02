"""How a space load attaches each assistant's selected prompt.

Every hidden-inclusive space load (each flow assistant write runs several)
attaches prompts to all assistants of the space, so the cost must stay linear
in assistants plus prompt rows.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from eneo.spaces.space_repo import HiddenAssistants, SpaceRepository


class _CountingAssistant:
    reads = 0

    def __init__(self) -> None:
        self._id = uuid4()
        self.mcp_servers: list[object] = []
        self.prompt: object | None = "unset"

    @property
    def id(self) -> UUID:
        type(self).reads += 1
        return self._id


class _CountingRows:
    """Prompt rows that count every row handed out by any iteration."""

    def __init__(self, rows: list[tuple[object, UUID]]) -> None:
        self._rows = rows
        self.visits = 0

    def __iter__(self):
        for row in self._rows:
            self.visits += 1
            yield row


def _result(*, assistants=None, rows=None):
    return SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: assistants),
        all=lambda: rows,
    )


def _repo(*, assistants, rows):
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[_result(assistants=assistants), _result(rows=rows)]
        )
    )
    return SpaceRepository(
        session=session,  # type: ignore[arg-type]
        tenant=SimpleNamespace(id=uuid4()),  # type: ignore[arg-type]
        factory=SimpleNamespace(),  # type: ignore[arg-type]
        file_content_loader=SimpleNamespace(),  # type: ignore[arg-type]
        app_repo=SimpleNamespace(),  # type: ignore[arg-type]
        assistant_repo=SimpleNamespace(),  # type: ignore[arg-type]
        completion_model_repo=SimpleNamespace(),  # type: ignore[arg-type]
        transcription_model_repo=SimpleNamespace(),  # type: ignore[arg-type]
        embedding_model_repo=SimpleNamespace(),  # type: ignore[arg-type]
        http_auth_encryption=SimpleNamespace(),  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_prompt_attachment_cost_is_linear_in_assistants_plus_prompt_rows():
    _CountingAssistant.reads = 0
    assistants = [_CountingAssistant() for _ in range(2000)]
    with_prompt = assistants[:1500]
    rows = _CountingRows(
        [(object(), assistant._id) for assistant in reversed(with_prompt)]
    )

    await _repo(assistants=assistants, rows=rows)._get_assistants(
        uuid4(), hidden_assistant_ids=HiddenAssistants.ALL
    )

    bound = 3 * (len(assistants) + len(with_prompt))
    assert _CountingAssistant.reads <= bound
    # Hoisting the id out of a per-assistant scan keeps id reads linear but
    # still visits every prompt row once per assistant.
    assert rows.visits <= bound


@pytest.mark.asyncio
async def test_each_assistant_gets_its_first_selected_prompt_row_or_none():
    first, second, without, last = (_CountingAssistant() for _ in range(4))
    first_prompt, first_later_prompt = object(), object()
    second_prompt, last_prompt = object(), object()
    rows = [
        (last_prompt, last._id),
        (first_prompt, first._id),
        (second_prompt, second._id),
        (first_later_prompt, first._id),
    ]
    assistants = [first, second, without, last]

    loaded = await _repo(assistants=assistants, rows=rows)._get_assistants(
        uuid4(), hidden_assistant_ids=HiddenAssistants.ALL
    )

    assert list(loaded) == assistants
    assert [assistant.prompt for assistant in loaded] == [
        first_prompt,
        second_prompt,
        None,
        last_prompt,
    ]
