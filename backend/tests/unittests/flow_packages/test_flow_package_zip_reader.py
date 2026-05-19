from __future__ import annotations

import json
import stat
import zipfile
from collections.abc import Mapping
from datetime import datetime, timezone
from io import BytesIO
from typing import cast

import pytest

from intric.flow_packages.domain.flow_package_checksum import (
    compose_content_checksum,
    hash_json_value,
)
from intric.flow_packages.domain.flow_package_draft import FlowPackageFlowDraft
from intric.flow_packages.domain.flow_package_errors import (
    FlowPackageErrorCode,
    FlowPackageValidationError,
    FlowPackageZipUnsafeReason,
)
from intric.flow_packages.domain.flow_package_manifest import (
    FlowPackageManifest,
    JsonObject,
)
from intric.flow_packages.domain.flow_package_provenance import FlowPackageProvenance
from intric.flow_packages.domain.flow_package_requirements import (
    FlowPackageModelRequirement,
    FlowPackageRequirementSet,
)
from intric.flow_packages.infrastructure import flow_package_zip_reader as reader
from intric.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    StepSpec,
)
from intric.flows.flow_resource_bindings import ResourceSlotKind, ResourceSlotRef


def test_valid_package_parses_to_typed_envelope() -> None:
    spec = _flow_spec()
    package_bytes = _package_bytes(spec=spec)

    envelope = reader.read_flow_package(package_bytes)

    assert envelope.spec == spec
    assert envelope.spec_hash == spec.spec_hash()
    assert envelope.manifest.package_id == "se.demo.flow"


def test_package_round_trip_preserves_flow_draft_spec() -> None:
    spec = _flow_spec(flow_name="Roundtrip")

    envelope = reader.read_flow_package(_package_bytes(spec=spec))

    assert envelope.spec.model_dump(mode="json") == spec.model_dump(mode="json")


def test_manifest_only_change_changes_content_checksum_not_spec_hash() -> None:
    base = reader.read_flow_package(_package_bytes(spec=_flow_spec()))
    manifest_changed = reader.read_flow_package(
        _package_bytes(spec=_flow_spec(), manifest_name="Changed")
    )

    assert base.spec_hash == manifest_changed.spec_hash
    assert base.content_checksum != manifest_changed.content_checksum


def test_draft_change_changes_spec_hash_and_content_checksum() -> None:
    base = reader.read_flow_package(_package_bytes(spec=_flow_spec()))
    draft_changed = reader.read_flow_package(
        _package_bytes(spec=_flow_spec(flow_name="Changed"))
    )

    assert base.spec_hash != draft_changed.spec_hash
    assert base.content_checksum != draft_changed.content_checksum


def test_tampered_checksum_is_rejected() -> None:
    docs = _package_docs()
    manifest = cast(JsonObject, docs[reader.MANIFEST_PATH])
    manifest["content_checksum"] = "f" * 64

    with pytest.raises(FlowPackageValidationError) as exc_info:
        reader.read_flow_package(_zip_docs(docs))

    assert exc_info.value.code is FlowPackageErrorCode.CHECKSUM_MISMATCH


@pytest.mark.parametrize(
    "path",
    [
        reader.MANIFEST_PATH,
        reader.FLOW_DRAFT_PATH,
        reader.REQUIREMENTS_PATH,
        reader.PROVENANCE_PATH,
    ],
)
@pytest.mark.parametrize("schema_version", [2, "1", 1.0])
def test_unsupported_schema_versions_are_rejected(
    path: str, schema_version: int | str | float
) -> None:
    docs = _package_docs()
    subdocument = cast(JsonObject, docs[path])
    subdocument["schema_version"] = schema_version

    with pytest.raises(FlowPackageValidationError) as exc_info:
        reader.read_flow_package(_zip_docs(docs))

    assert exc_info.value.code is FlowPackageErrorCode.SCHEMA_UNSUPPORTED


def test_uuid_shaped_draft_resource_ref_is_rejected_as_not_portable() -> None:
    docs = _package_docs()
    flow_draft = cast(JsonObject, docs[reader.FLOW_DRAFT_PATH])
    spec = cast(JsonObject, flow_draft["spec"])
    steps = cast(list[JsonObject], spec["steps"])
    assistant_spec = cast(JsonObject, steps[0]["assistant_spec"])
    assistant_spec["model_ref"] = "11111111-1111-4111-8111-111111111111"

    with pytest.raises(FlowPackageValidationError) as exc_info:
        reader.read_flow_package(_zip_docs(docs))

    assert exc_info.value.code is FlowPackageErrorCode.LOCAL_RESOURCE_REFS_NOT_PORTABLE


def test_bad_zip_is_rejected() -> None:
    assert_zip_unsafe(b"not a zip", FlowPackageZipUnsafeReason.BAD_ZIP)


def test_too_many_entries_is_rejected() -> None:
    assert_zip_unsafe(
        _zip_raw(
            {
                reader.MANIFEST_PATH: b"{}",
                reader.FLOW_DRAFT_PATH: b"{}",
                reader.REQUIREMENTS_PATH: b"{}",
                reader.PROVENANCE_PATH: b"{}",
                "extra.json": b"{}",
            }
        ),
        FlowPackageZipUnsafeReason.TOO_MANY_ENTRIES,
    )


def test_directory_entry_is_rejected() -> None:
    assert_zip_unsafe(
        _zip_raw(
            {
                "folder/": b"",
                reader.MANIFEST_PATH: b"{}",
                reader.FLOW_DRAFT_PATH: b"{}",
                reader.REQUIREMENTS_PATH: b"{}",
            }
        ),
        FlowPackageZipUnsafeReason.DIRECTORY_ENTRY,
    )


def test_symlink_entry_is_rejected() -> None:
    info = zipfile.ZipInfo(reader.MANIFEST_PATH)
    info.external_attr = (stat.S_IFLNK | 0o777) << 16

    assert_zip_unsafe(
        _zip_infos(
            [
                (info, b"target"),
                (zipfile.ZipInfo(reader.FLOW_DRAFT_PATH), b"{}"),
                (zipfile.ZipInfo(reader.REQUIREMENTS_PATH), b"{}"),
                (zipfile.ZipInfo(reader.PROVENANCE_PATH), b"{}"),
            ]
        ),
        FlowPackageZipUnsafeReason.SYMLINK_ENTRY,
    )


@pytest.mark.parametrize(
    ("path", "reason"),
    [
        ("/manifest.json", FlowPackageZipUnsafeReason.ABSOLUTE_PATH),
        ("../manifest.json", FlowPackageZipUnsafeReason.PATH_TRAVERSAL),
        ("folder\\manifest.json", FlowPackageZipUnsafeReason.BACKSLASH_PATH),
    ],
)
def test_unsafe_paths_are_rejected(
    path: str, reason: FlowPackageZipUnsafeReason
) -> None:
    assert_zip_unsafe(
        _zip_raw(
            {
                path: b"{}",
                reader.FLOW_DRAFT_PATH: b"{}",
                reader.REQUIREMENTS_PATH: b"{}",
                reader.PROVENANCE_PATH: b"{}",
            }
        ),
        reason,
    )


def test_duplicate_entry_is_rejected() -> None:
    assert_zip_unsafe(
        _zip_infos(
            [
                (zipfile.ZipInfo(reader.MANIFEST_PATH), b"{}"),
                (zipfile.ZipInfo(reader.MANIFEST_PATH), b"{}"),
                (zipfile.ZipInfo(reader.FLOW_DRAFT_PATH), b"{}"),
                (zipfile.ZipInfo(reader.REQUIREMENTS_PATH), b"{}"),
            ]
        ),
        FlowPackageZipUnsafeReason.DUPLICATE_ENTRY,
    )


def test_unknown_entry_is_rejected() -> None:
    assert_zip_unsafe(
        _zip_raw(
            {
                "unknown.json": b"{}",
                reader.MANIFEST_PATH: b"{}",
                reader.FLOW_DRAFT_PATH: b"{}",
                reader.REQUIREMENTS_PATH: b"{}",
            }
        ),
        FlowPackageZipUnsafeReason.UNKNOWN_ENTRY,
    )


def test_missing_required_entry_is_rejected() -> None:
    assert_zip_unsafe(
        _zip_raw(
            {
                reader.MANIFEST_PATH: b"{}",
                reader.FLOW_DRAFT_PATH: b"{}",
                reader.REQUIREMENTS_PATH: b"{}",
            }
        ),
        FlowPackageZipUnsafeReason.MISSING_REQUIRED_ENTRY,
    )


def test_compressed_entry_too_large_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reader, "MAX_PER_ENTRY_COMPRESSED_BYTES", 8)

    assert_zip_unsafe(
        _zip_raw({reader.MANIFEST_PATH: b'{"schema_version":1}'}),
        FlowPackageZipUnsafeReason.COMPRESSED_ENTRY_TOO_LARGE,
    )


def test_uncompressed_entry_too_large_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reader, "MAX_PER_ENTRY_UNCOMPRESSED_BYTES", 8)

    assert_zip_unsafe(
        _zip_raw({reader.MANIFEST_PATH: b'{"schema_version":1}'}),
        FlowPackageZipUnsafeReason.UNCOMPRESSED_ENTRY_TOO_LARGE,
    )


def test_total_uncompressed_too_large_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reader, "MAX_TOTAL_UNCOMPRESSED_BYTES", 8)

    assert_zip_unsafe(
        _zip_raw({reader.MANIFEST_PATH: b'{"schema_version":1}'}),
        FlowPackageZipUnsafeReason.TOTAL_UNCOMPRESSED_TOO_LARGE,
    )


def test_decompression_ratio_too_high_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reader, "MAX_DECOMPRESSION_RATIO", 1)

    assert_zip_unsafe(
        _zip_raw({reader.MANIFEST_PATH: b"a" * 100}),
        FlowPackageZipUnsafeReason.DECOMPRESSION_RATIO_TOO_HIGH,
    )


def test_json_too_large_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reader, "MAX_JSON_BYTES", 8)

    assert_zip_unsafe(
        _zip_raw({reader.MANIFEST_PATH: b'{"schema_version":1}'}),
        FlowPackageZipUnsafeReason.JSON_TOO_LARGE,
    )


def assert_zip_unsafe(
    package_bytes: bytes,
    reason: FlowPackageZipUnsafeReason,
) -> None:
    with pytest.raises(FlowPackageValidationError) as exc_info:
        reader.read_flow_package(package_bytes)

    assert exc_info.value.code is FlowPackageErrorCode.ZIP_UNSAFE
    assert exc_info.value.context["reason"] == reason.value


def _package_bytes(
    *,
    spec: FlowDraftSpecCore | None = None,
    manifest_name: str = "Demo Flow",
) -> bytes:
    return _zip_docs(_package_docs(spec=spec, manifest_name=manifest_name))


def _package_docs(
    *,
    spec: FlowDraftSpecCore | None = None,
    manifest_name: str = "Demo Flow",
) -> dict[str, JsonObject]:
    if spec is None:
        spec = _flow_spec()
    draft = FlowPackageFlowDraft(schema_version=1, spec=spec)
    requirements = FlowPackageRequirementSet(
        schema_version=1,
        requirements=[
            FlowPackageModelRequirement(
                slot_ref=_slot_ref(ResourceSlotKind.MODEL, "structured")
            )
        ],
    )
    provenance = FlowPackageProvenance(
        schema_version=1,
        exported_at=datetime(2026, 5, 18, tzinfo=timezone.utc),
        source_instance_id="source-instance",
    )
    manifest = FlowPackageManifest(
        schema_version=1,
        package_id="se.demo.flow",
        package_version="1.0.0",
        name=manifest_name,
        content_checksum="0" * 64,
    )
    content_checksum = compose_content_checksum(
        spec_hash=spec.spec_hash(),
        manifest_hash=hash_json_value(manifest.canonical_hash_input()),
        requirements_hash=hash_json_value(
            cast(JsonObject, requirements.model_dump(mode="json"))
        ),
        provenance_hash=hash_json_value(
            cast(JsonObject, provenance.model_dump(mode="json"))
        ),
    )
    manifest = manifest.model_copy(update={"content_checksum": content_checksum})
    return {
        reader.MANIFEST_PATH: cast(JsonObject, manifest.model_dump(mode="json")),
        reader.FLOW_DRAFT_PATH: cast(JsonObject, draft.model_dump(mode="json")),
        reader.REQUIREMENTS_PATH: cast(
            JsonObject, requirements.model_dump(mode="json")
        ),
        reader.PROVENANCE_PATH: cast(JsonObject, provenance.model_dump(mode="json")),
    }


def _flow_spec(flow_name: str = "Demo") -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name=flow_name,
        steps=[
            StepSpec(
                plan_step_ref="extract",
                name="Extract",
                assistant_spec=AssistantSpec(
                    instructions="Extract facts.",
                    model_ref="model.structured",
                ),
                input_source=InputSource.FLOW_INPUT,
            )
        ],
    )


def _slot_ref(kind: ResourceSlotKind, slot: str) -> ResourceSlotRef:
    return ResourceSlotRef(kind=kind, slot=slot, label=slot.replace("-", " ").title())


def _zip_docs(docs: Mapping[str, JsonObject]) -> bytes:
    payloads = {
        path: json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()
        for path, value in docs.items()
    }
    return _zip_raw(payloads)


def _zip_raw(payloads: Mapping[str, bytes]) -> bytes:
    infos = [(zipfile.ZipInfo(path), payload) for path, payload in payloads.items()]
    return _zip_infos(infos)


def _zip_infos(entries: list[tuple[zipfile.ZipInfo, bytes]]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for info, payload in entries:
            info.compress_type = zipfile.ZIP_DEFLATED
            package.writestr(info, payload)
    return buffer.getvalue()
