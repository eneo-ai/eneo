from __future__ import annotations

import base64
import hashlib
import io
import zipfile
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from eneo.files.docx_template_validation import MAX_TEMPLATE_UNCOMPRESSED_BYTES
from eneo.flow_packages.api import flow_package_router
from eneo.flow_packages.application import (
    flow_package_template_uploads as uploads_module,
)
from eneo.flow_packages.application.flow_package_template_uploads import (
    MAX_TEMPLATE_UPLOADS_BASE64_CHARS,
    FlowPackageTemplateUpload,
    resolve_flow_package_template_files,
)
from eneo.flow_packages.domain import flow_package_templates as templates_module
from eneo.flow_packages.domain.flow_package_envelope import FlowPackageEnvelope
from eneo.flow_packages.domain.flow_package_errors import (
    FlowPackageErrorCode,
    FlowPackageValidationError,
)
from eneo.flow_packages.domain.flow_package_requirements import (
    FlowPackageTemplateAssetRequirement,
)
from eneo.flows.application.flow_authoring_command import TemplateImportIntent
from eneo.flows.application.flow_draft_materialization import (
    FlowDraftChangeSet,
    FlowDraftCompiledStep,
    FlowDraftStepChangeKind,
)
from eneo.flows.application.flow_template_attachment_materialization import (
    materialize_template_imports,
)
from eneo.flows.enums import FlowOutputMode
from eneo.flows.flow_resource_bindings import ResourceSlotKind, ResourceSlotRef
from eneo.main.exceptions import FileTooLargeException
from tests.docx_template_fixtures import control_template_bytes

_SLOTS = 256


def _slot(index: int) -> ResourceSlotRef:
    return ResourceSlotRef(
        kind=ResourceSlotKind.TEMPLATE_ASSET, slot=f"slot-{index}", label="T.docx"
    )


def _docx() -> bytes:
    return control_template_bytes(rich=[("dokument", "Dokument", "")])


class _FakeEnvelope:
    """The parts of an envelope the resolver reads, with its resolution memo."""

    def __init__(self, *, requirements: object, template_payloads: dict[str, bytes]):
        self.requirements = requirements
        self.template_payloads = template_payloads
        self._memo: tuple[int, object] | None = None

    def cached_template_resolution(self) -> object | None:
        if self._memo is not None and self._memo[0] == id(self.template_payloads):
            return self._memo[1]
        return None

    def remember_template_resolution(self, resolution: object) -> None:
        self._memo = (id(self.template_payloads), resolution)


def _envelope_with_slots(
    count: int, content: bytes, *, included: bool = False
) -> FlowPackageEnvelope:
    checksum = hashlib.sha256(content).hexdigest()
    requirements = [
        FlowPackageTemplateAssetRequirement.model_validate(
            {
                "slot_ref": _slot(index),
                "used_by_steps": [f"s{index}"],
                "template": {
                    "filename": "T.docx",
                    "checksum": hashlib.sha256(content).hexdigest(),
                    "size_bytes": len(content),
                    "fields": [{"name": "dokument", "kind": "rich"}],
                    "asset_path": f"templates/{checksum}.docx" if included else None,
                },
            }
        )
        for index in range(count)
    ]
    return cast(
        FlowPackageEnvelope,
        _FakeEnvelope(
            requirements=SimpleNamespace(requirements=requirements),
            template_payloads=(
                {f"templates/{checksum}.docx": content} if included else {}
            ),
        ),
    )


def _upload(index: int, content: bytes) -> FlowPackageTemplateUpload:
    return FlowPackageTemplateUpload(
        template_ref=_slot(index).ref,
        filename="T.docx",
        content_base64=base64.b64encode(content).decode(),
    )


def _spy_inspection(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    real = uploads_module.inspect_docx_template_bytes

    def counting(content: bytes, *, filename: str):  # type: ignore[no-untyped-def]
        calls.append(filename)
        return real(content, filename=filename)

    monkeypatch.setattr(uploads_module, "inspect_docx_template_bytes", counting)
    return calls


def test_one_packaged_docx_in_256_slots_is_inspected_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = _docx()
    calls = _spy_inspection(monkeypatch)

    files = resolve_flow_package_template_files(
        _envelope_with_slots(40, content, included=True)
    )

    assert len(files) == 40
    assert len(calls) == 1


def test_one_docx_uploaded_for_many_slots_is_inspected_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = _docx()
    calls = _spy_inspection(monkeypatch)

    files = resolve_flow_package_template_files(
        _envelope_with_slots(30, content),
        [_upload(index, content) for index in range(30)],
    )

    assert len(files) == 30
    assert len(calls) == 1


def _big_unpacked_docx(marker: str, unpacked_bytes: int) -> bytes:
    """A small file that unpacks to ``unpacked_bytes`` (all zeros compress away)."""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<w:document/>")
        archive.writestr("word/padding.bin", bytes(unpacked_bytes))
        archive.writestr("marker.txt", marker)
    return buffer.getvalue()


def test_the_unpacked_budget_counts_every_slot_not_distinct_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _spy_inspection(monkeypatch)
    # One file that unpacks to ~40 MiB, reused by three slots: 120 MiB of work.
    content = _big_unpacked_docx("one", 40 * 1024 * 1024)
    envelope = _envelope_with_slots(3, content, included=True)

    with pytest.raises(FlowPackageValidationError) as error:
        resolve_flow_package_template_files(envelope)

    assert error.value.code is FlowPackageErrorCode.TEMPLATE_FILE_INVALID
    assert "too large when unpacked" in str(error.value)
    assert calls == []


def test_256_slots_of_a_large_file_are_refused_up_front_but_small_reuse_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _spy_inspection(monkeypatch)
    big = _big_unpacked_docx("big", MAX_TEMPLATE_UNCOMPRESSED_BYTES - 1024)
    with pytest.raises(FlowPackageValidationError) as error:
        resolve_flow_package_template_files(
            _envelope_with_slots(_SLOTS, big, included=True)
        )
    assert "too large when unpacked" in str(error.value)
    assert calls == []

    small = _docx()
    assert (
        len(
            resolve_flow_package_template_files(
                _envelope_with_slots(40, small, included=True)
            )
        )
        == 40
    )


def test_distinct_big_uploads_over_the_budget_are_refused_before_inspection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _spy_inspection(monkeypatch)
    each = 40 * 1024 * 1024
    contents = [_big_unpacked_docx(f"t{index}", each) for index in range(3)]

    with pytest.raises(FlowPackageValidationError) as error:
        resolve_flow_package_template_files(
            _envelope_with_slots(3, contents[0]),
            [_upload(index, content) for index, content in enumerate(contents)],
        )

    assert "too large when unpacked" in str(error.value)
    assert calls == []


@pytest.mark.parametrize("name", ["../Other.docx", "Bad\x00Name.docx", "a/b.docx"])
def test_every_slots_filename_is_validated_even_when_its_bytes_were_seen(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    content = _docx()
    first = _upload(0, content)
    second = FlowPackageTemplateUpload(
        template_ref=_slot(1).ref,
        filename=name,
        content_base64=base64.b64encode(content).decode(),
    )

    with pytest.raises(FlowPackageValidationError) as error:
        resolve_flow_package_template_files(
            _envelope_with_slots(2, content), [first, second]
        )

    assert error.value.code is FlowPackageErrorCode.TEMPLATE_FILE_INVALID
    assert error.value.context["slot_ref"] == _slot(1).ref


def test_each_payload_is_hashed_once(monkeypatch: pytest.MonkeyPatch) -> None:
    content = _docx()
    uploaded_envelope = _envelope_with_slots(30, content)
    uploads = [_upload(index, content) for index in range(30)]
    packaged_envelope = _envelope_with_slots(40, content, included=True)
    descriptors = {
        requirement.slot_ref.ref: requirement.template
        for requirement in packaged_envelope.requirements.requirements  # type: ignore[union-attr]
        if isinstance(requirement, FlowPackageTemplateAssetRequirement)
        and requirement.template is not None
    }
    hashes: list[int] = []
    real = hashlib.sha256

    def counting(data: bytes = b"") -> object:
        hashes.append(len(data))
        return real(data)

    monkeypatch.setattr(hashlib, "sha256", counting)

    # Uploaded: one hash per payload, none again at inspection.
    resolve_flow_package_template_files(uploaded_envelope, uploads)
    assert len(hashes) == 30

    # Packaged: the envelope check hashes a payload shared by 40 slots once, and
    # resolving carries that checksum instead of hashing again.
    hashes.clear()
    templates_module.validate_package_template_payloads(
        descriptors, packaged_envelope.template_payloads
    )
    assert len(hashes) == 1
    hashes.clear()
    resolve_flow_package_template_files(packaged_envelope)
    assert hashes == []


def test_reading_a_package_does_not_open_its_word_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from eneo.flow_packages.infrastructure.flow_package_zip_reader import (
        read_flow_package,
    )
    from eneo.flow_packages.infrastructure.flow_package_zip_writer import (
        write_flow_package,
    )
    from tests.unittests.flow_packages.test_flow_package_templates import (
        _template_envelope,
    )

    package = write_flow_package(_template_envelope())
    calls = _spy_inspection(monkeypatch)

    envelope = read_flow_package(package)

    # Resolving is the caller's explicit, single step.
    assert calls == []
    resolve_flow_package_template_files(envelope)
    assert len(calls) == 1


def test_replacement_uploads_over_the_aggregate_encoded_limit_are_refused_before_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decoded: list[int] = []
    real = uploads_module.base64.b64decode
    monkeypatch.setattr(
        uploads_module.base64,
        "b64decode",
        lambda *args, **kwargs: decoded.append(1) or real(*args, **kwargs),
    )
    chunk = MAX_TEMPLATE_UPLOADS_BASE64_CHARS // 3 + 4
    uploads = [
        FlowPackageTemplateUpload(
            template_ref=_slot(index).ref,
            filename="T.docx",
            content_base64="A" * chunk,
        )
        for index in range(4)
    ]

    with pytest.raises(FlowPackageValidationError) as error:
        resolve_flow_package_template_files(_envelope_with_slots(4, _docx()), uploads)

    assert error.value.code is FlowPackageErrorCode.TEMPLATE_FILE_INVALID
    assert decoded == []


def _changeset(count: int) -> FlowDraftChangeSet:
    steps = [
        FlowDraftCompiledStep(
            plan_step_ref=f"s{index}",
            change_kind=FlowDraftStepChangeKind.ADDED,
            step_order=index + 1,
            user_description=None,
            input_source="flow_input",
            input_type="text",
            output_mode=FlowOutputMode.TEMPLATE_FILL,
            output_type="docx",
            output_config={
                "template_ref": _slot(index).ref,
                "bindings": {"dokument": "{{flow_input.text}}"},
            },
        )
        for index in range(count)
    ]
    return FlowDraftChangeSet(flow_name="F", flow_description="", compiled_steps=steps)


@pytest.mark.anyio
async def test_each_slot_keeps_its_own_asset_and_reviewed_filename() -> None:
    content = _docx()
    created: list[str] = []

    async def create(*, flow_id: UUID, filename: str, content: bytes) -> object:
        created.append(filename)
        return SimpleNamespace(
            id=UUID(int=len(created)),
            name=filename,
            checksum="c",
            placeholders=["dokument"],
        )

    service = SimpleNamespace(create_asset_from_bytes=create)

    changeset, bindings = await materialize_template_imports(
        intents=tuple(
            TemplateImportIntent(slot_ref=_slot(index), filename=name, content=content)
            for index, name in enumerate(["First.docx", "Second.docx"])
        ),
        changeset=_changeset(2),
        flow_id=UUID(int=9),
        template_asset_service=cast(object, service),  # type: ignore[arg-type]
    )

    assert created == ["First.docx", "Second.docx"]
    assert [binding.local_id for binding in bindings] == [UUID(int=1), UUID(int=2)]
    assert [
        step.output_config["template_name"] for step in changeset.compiled_steps
    ] == [  # type: ignore[index]
        "First.docx",
        "Second.docx",
    ]


def test_import_routes_read_the_body_under_one_cap_derived_from_the_package_limits() -> (
    None
):
    cap = flow_package_router.MAX_IMPORT_REQUEST_BYTES
    assert cap == (
        flow_package_router.MAX_PACKAGE_BASE64_CHARS
        + flow_package_router.MAX_TEMPLATE_UPLOADS_JSON_BYTES
    )
    assert flow_package_router.space_router.routes
    assert all(
        type(route).__name__ == "CappedBodyRoute"
        for route in flow_package_router.space_router.routes
    )


_PARSED: list[bool] = []


class _Body(BaseModel):
    data: str

    def model_post_init(self, _context: object) -> None:
        _PARSED.append(True)


def test_an_over_limit_import_body_is_refused_before_it_is_parsed() -> None:
    _PARSED.clear()
    router = APIRouter(route_class=flow_package_router.space_router.route_class)

    @router.post("/imports/")
    async def endpoint(body: _Body) -> dict[str, bool]:
        return {"ok": True}

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=True)
    over = flow_package_router.MAX_IMPORT_REQUEST_BYTES + 1

    with pytest.raises(FileTooLargeException) as error:
        client.post(
            "/imports/",
            content=b'{"data": "' + b"a" * over + b'"}',
            headers={"content-type": "application/json"},
        )

    assert error.value.code == "flow_request_body_too_large"
    assert _PARSED == []
    # A body within the cap is parsed as usual.
    assert client.post("/imports/", json={"data": "ok"}).status_code == 200
    assert _PARSED == [True]
