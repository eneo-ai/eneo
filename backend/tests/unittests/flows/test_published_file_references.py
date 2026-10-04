from __future__ import annotations

import runpy
from pathlib import Path
from typing import Any, get_args
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel

from eneo.flows.assistant_execution_snapshot import AssistantExecutionSurfaceV2
from eneo.flows.domain.step_config import _TEMPLATE_CONFIG_KEYS
from eneo.flows.published_definition import (
    FLOW_DEFINITION_SCHEMA_VERSION,
    published_file_references,
)


def _definition(*steps: object) -> dict[str, object]:
    return {"schema_version": FLOW_DEFINITION_SCHEMA_VERSION, "steps": list(steps)}


def _step(
    *,
    output_config: object = None,
    attachments: object = None,
    snapshot: object = ...,
) -> dict[str, object]:
    if snapshot is ...:
        snapshot = {"attachments": attachments}
    return {"output_config": output_config, "assistant_snapshot": snapshot}


def test_references_collect_template_assets_template_files_and_attachments() -> None:
    asset, template_file, attached, other = uuid4(), uuid4(), uuid4(), uuid4()

    refs = published_file_references(
        _definition(
            _step(
                output_config={
                    "template_asset_id": str(asset),
                    "template_file_id": str(template_file),
                },
                attachments=[{"file_id": str(attached), "checksum": "c"}],
            ),
            _step(attachments=[{"file_id": str(other), "checksum": "c"}]),
        )
    )

    assert refs.template_asset_ids == {asset}
    assert refs.file_ids == {template_file, attached, other}


def test_references_ignore_knowledge_and_unrelated_ids() -> None:
    refs = published_file_references(
        _definition(
            _step(
                output_config={"unrelated_id": str(uuid4())},
                snapshot={
                    "knowledge_refs": [{"kind": "collection", "id": str(uuid4())}],
                    "assistant_id": str(uuid4()),
                    "attachments": [],
                },
            )
        )
    )

    assert not refs.file_ids and not refs.template_asset_ids


_BACKFILL_MIGRATION = (
    Path(__file__).parents[3]
    / "alembic/versions/202610021015_backfill_flow_version_file_references.py"
)
_MALFORMED_DEFINITIONS: list[Any] = [
    {},
    {"schema_version": FLOW_DEFINITION_SCHEMA_VERSION},
    {"schema_version": FLOW_DEFINITION_SCHEMA_VERSION, "steps": None},
    {"schema_version": FLOW_DEFINITION_SCHEMA_VERSION, "steps": {}},
    {
        "schema_version": 99,
        "steps": [_step(attachments=[{"file_id": str(uuid4())}])],
    },
    _definition("not-a-step", None, 3, []),
    _definition({}),
    _definition(_step(snapshot=None)),
    _definition(_step(snapshot=[])),
    _definition(_step(snapshot="x")),
    _definition(_step(attachments=None)),
    _definition(_step(attachments={})),
    _definition(_step(attachments=[])),
    _definition(_step(attachments=[None, 5, "x", [], {}])),
    _definition(_step(attachments=[{"file_id": None}, {"file_id": ""}])),
    _definition(_step(attachments=[{"file_id": 7}, {"file_id": "not-a-uuid"}])),
    _definition(_step(output_config=[])),
    _definition(_step(output_config={"template_asset_id": 5})),
    _definition(_step(output_config={"template_file_id": ["x"]})),
]


@pytest.mark.parametrize("definition", _MALFORMED_DEFINITIONS)
def test_references_read_malformed_shapes_as_no_references(
    definition: dict[str, object],
) -> None:
    refs = published_file_references(definition)

    assert not refs.file_ids and not refs.template_asset_ids


def test_references_keep_readable_ids_next_to_unreadable_ones() -> None:
    good_asset, good_file = uuid4(), uuid4()

    refs = published_file_references(
        _definition(
            _step(output_config={"template_asset_id": "broken"}),
            _step(
                output_config={"template_asset_id": str(good_asset)},
                attachments=[{"file_id": "broken"}, {"file_id": str(good_file)}],
            ),
        )
    )

    assert refs.template_asset_ids == {good_asset}
    assert refs.file_ids == {good_file}


def _file_field_paths(model: type[BaseModel], prefix: str = "") -> set[str]:
    paths: set[str] = set()
    for name, field in model.model_fields.items():
        annotation: Any = field.annotation
        nested = [
            arg
            for arg in (get_args(annotation) or (annotation,))
            if isinstance(arg, type)
        ]
        for arg in nested:
            if issubclass(arg, BaseModel):
                paths |= _file_field_paths(arg, f"{prefix}{name}.")
        if name.endswith(("file_id", "file_ids")):
            paths.add(f"{prefix}{name}")
    return paths


def test_every_file_id_field_of_the_assistant_snapshot_model_is_read() -> None:
    # A new file-id field on the frozen assistant surface must be added to the
    # reader before this passes: the walk finds fields the reader does not.
    assert _file_field_paths(AssistantExecutionSurfaceV2) == {"attachments.file_id"}
    attached = uuid4()
    refs = published_file_references(
        _definition(_step(attachments=[{"file_id": str(attached), "checksum": "c"}]))
    )
    assert refs.file_ids == {attached}


@pytest.mark.parametrize(
    "key",
    sorted(k for k in _TEMPLATE_CONFIG_KEYS if k.endswith(("_file_id", "_asset_id"))),
)
def test_every_template_id_key_of_the_step_config_is_read(key: str) -> None:
    value: UUID = uuid4()

    refs = published_file_references(
        _definition(_step(output_config={key: str(value)}))
    )

    assert value in refs.file_ids | refs.template_asset_ids


def test_frozen_backfill_reader_names_what_the_writer_reader_names() -> None:
    # The migration carries its own frozen reader; for today's schema it must
    # agree with the owner on every shape, malformed ones included.
    named_ids = runpy.run_path(str(_BACKFILL_MIGRATION))["_named_ids"]
    asset, template_file, attached = uuid4(), uuid4(), uuid4()
    full = _definition(
        _step(
            output_config={
                "template_asset_id": str(asset),
                "template_file_id": str(template_file),
            },
            attachments=[{"file_id": str(attached), "checksum": "c"}],
        ),
        _step(output_config={"template_asset_id": "broken"}, attachments=[None]),
    )

    for definition in [*_MALFORMED_DEFINITIONS, full]:
        refs = published_file_references(definition)
        file_ids, asset_ids = named_ids(definition)
        assert (file_ids, asset_ids) == (
            set(refs.file_ids),
            set(refs.template_asset_ids),
        )
