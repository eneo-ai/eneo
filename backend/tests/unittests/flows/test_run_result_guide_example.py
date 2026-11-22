"""The integration guide's example of the run result body has the keys the
producer sends, at the top and per kind of entry, so the guide cannot describe
a body Eneo no longer sends."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from eneo.files.file_models import FileType
from eneo.flows.api.flow_run_contract_models import (
    FlowRunDeliverablePublic,
    FlowRunTextDeliverablePublic,
)
from eneo.flows.enums import FlowOutputType
from eneo.flows.flow_run_step_result_file import FlowRunStepResultFile
from eneo.flows.runtime.run_result_body import (
    RUN_RESULT_SCHEMA,
    RunResultText,
    run_result_body,
)

BACKEND_ROOT = Path(__file__).resolve().parents[3]
GUIDE = (
    BACKEND_ROOT.parent
    / "frontend"
    / "apps"
    / "docs-site"
    / "src"
    / "content"
    / "guides"
    / "flows"
    / "integrating-flows.mdx"
)
CONTENT = b"PK\x03\x04document"


def _guide_body() -> dict[str, object]:
    blocks = re.findall(r"```json\n(.*?)\n```", GUIDE.read_text(), flags=re.S)
    # Other examples in the guide are excerpts, not always whole JSON.
    bodies = [block for block in blocks if f'"schema": "{RUN_RESULT_SCHEMA}"' in block]
    assert len(bodies) == 1, "the guide shows one example of the run result body"
    body = json.loads(bodies[0])
    assert isinstance(body, dict)
    return body


def _produced_body() -> dict[str, object]:
    step_id = uuid4()
    file = FlowRunStepResultFile.model_validate(
        {
            "flow_run_id": uuid4(),
            "flow_id": uuid4(),
            "tenant_id": uuid4(),
            "step_result_id": uuid4(),
            "step_id": step_id,
            "step_order": 3,
            "attempt_no": 1,
            "file_id": uuid4(),
            "ordinal": 0,
            "source": "declared_artifact",
            "name": "Minutes.docx",
            "checksum": hashlib.sha256(CONTENT).hexdigest(),
            "size": len(CONTENT),
            "mimetype": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "file_type": FileType.DOCUMENT,
            "availability": "available",
        }
    )
    text = RunResultText(
        deliverable=FlowRunTextDeliverablePublic(
            kind="text",
            step_id=uuid4(),
            step_order=2,
            label="Minutes",
            output_type=FlowOutputType.TEXT,
            delivery="payload",
        ),
        inline="# Minutes",
    )
    document = FlowRunDeliverablePublic(
        kind="artifact",
        step_id=step_id,
        step_order=3,
        label="Minutes",
        output_type=FlowOutputType.DOCX,
        files=[file],
    )
    run = SimpleNamespace(
        id=uuid4(),
        flow_id=uuid4(),
        created_at=datetime(2026, 11, 20, 8, 0, tzinfo=timezone.utc),
        finished_at=datetime(2026, 11, 20, 8, 5, tzinfo=timezone.utc),
        run_label="Weekly stand-up",
        run_date=date(2026, 11, 20),
    )
    body = run_result_body(
        run=run,  # pyright: ignore[reportArgumentType]
        parts=[text, document],
        contents={file.file_id: CONTENT},
    )
    assert isinstance(body, dict)
    return body


def _entries_by_kind(body: dict[str, object]) -> dict[str, dict[str, object]]:
    entries = body["deliverables"]
    assert isinstance(entries, list)
    by_kind = {entry["kind"]: entry for entry in entries}
    assert set(by_kind) == {"text", "artifact"}, (
        "the guide shows one entry of each kind"
    )
    return by_kind


def test_the_guide_shows_the_body_the_producer_sends() -> None:
    guide, produced = _guide_body(), _produced_body()

    assert set(guide) == set(produced)
    guide_entries, produced_entries = (
        _entries_by_kind(guide),
        _entries_by_kind(produced),
    )
    for kind in ("text", "artifact"):
        assert set(guide_entries[kind]) == set(produced_entries[kind]), kind
    [guide_file] = guide_entries["artifact"]["files"]  # type: ignore[misc]
    [produced_file] = produced_entries["artifact"]["files"]  # type: ignore[misc]
    assert set(guide_file) == set(produced_file)
    assert re.fullmatch(r"[0-9a-f]{64}", guide_file["checksum"])
    assert re.fullmatch(r"[0-9a-f]{64}", produced_file["checksum"])
