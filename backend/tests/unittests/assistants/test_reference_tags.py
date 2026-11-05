import random
from types import SimpleNamespace
from uuid import UUID

from eneo.assistants.assistant_service import get_references
from eneo.assistants.reference_tags import InlineReferenceScanner


def _blob(hex_id: str) -> SimpleNamespace:
    return SimpleNamespace(id=UUID(hex_id))


def _tag(blob: SimpleNamespace) -> str:
    return f'<inref id="{str(blob.id)[:8]}"/>'


def test_each_chunk_gets_what_a_full_rescan_of_the_answer_gives() -> None:
    rng = random.Random(7)
    blobs = [_blob(f"{i:08x}-0000-4000-8000-{i:012x}") for i in range(12)]
    # Two blobs share an eight-character prefix: the first one listed wins.
    blobs.append(_blob("00000003-ffff-4000-8000-000000000099"))
    for _ in range(300):
        parts = []
        for _ in range(rng.randint(0, 40)):
            choice = rng.random()
            if choice < 0.3:
                parts.append(_tag(rng.choice(blobs)))
            elif choice < 0.35:
                parts.append('<inref id="deadbeef"/>')  # cites nothing retrieved
            elif choice < 0.4:
                parts.append('<inref id="0000000')  # an unfinished tag
            else:
                parts.append("ord " * rng.randint(0, 5))
        text = "".join(parts)
        cuts = (
            sorted(rng.sample(range(1, len(text)), min(len(text) - 1, 30)))
            if text
            else []
        )
        scanner = InlineReferenceScanner(blobs)
        answer = ""
        for start, end in zip([0, *cuts], [*cuts, len(text)]):
            answer += text[start:end]
            expected = get_references(answer, blobs, version=2)
            got = scanner.references(answer)
            assert [id(blob) for blob in got] == [id(blob) for blob in expected]


def test_each_call_returns_a_new_list() -> None:
    blob = _blob("abcdef01-0000-4000-8000-000000000001")
    scanner = InlineReferenceScanner([blob])
    first = scanner.references(_tag(blob))
    second = scanner.references(_tag(blob) + " more")
    assert first == second == [blob]
    assert first is not second
