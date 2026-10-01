from __future__ import annotations

import base64
import binascii
import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from eneo.files.docx_template_validation import (
    docx_template_archive_metrics,
)
from eneo.flow_packages.domain.flow_package_envelope import FlowPackageEnvelope
from eneo.flow_packages.domain.flow_package_errors import (
    FlowPackageErrorCode,
    FlowPackageValidationError,
)
from eneo.flow_packages.domain.flow_package_limits import (
    MAX_FLOW_PACKAGE_BYTES,
    MAX_FLOW_PACKAGE_TEMPLATES_UNPACKED_BYTES,
)
from eneo.flow_packages.domain.flow_package_requirements import (
    FlowPackageTemplateAssetRequirement,
)
from eneo.flow_packages.domain.flow_package_templates import (
    FlowPackageTemplateDescriptor,
    FlowPackageTemplateField,
    FlowPackageTemplateFile,
    require_package_template_fields,
    validate_template_filename,
)
from eneo.flows.flow_authoring_spec import MAX_FLOW_AUTHORING_STEPS
from eneo.flows.runtime.docx_template_runtime import inspect_docx_template_bytes
from eneo.main.exceptions import BadRequestException, FileNotSupportedException

# The most base64 text all replacement uploads of one import may carry together:
# the encoding of the package byte cap, which also bounds their decoded total.
MAX_TEMPLATE_UPLOADS_BASE64_CHARS = ((MAX_FLOW_PACKAGE_BYTES + 2) // 3) * 4
MAX_TEMPLATE_UPLOADS_JSON_BYTES = MAX_TEMPLATE_UPLOADS_BASE64_CHARS + 256 * 1024


class FlowPackageTemplateUpload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    template_ref: str = Field(min_length=1, max_length=255)
    filename: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(
        min_length=1, max_length=MAX_TEMPLATE_UPLOADS_BASE64_CHARS
    )


def inspect_package_template(
    content: bytes,
    *,
    filename: str,
    included: bool,
    checksum: str | None = None,
) -> FlowPackageTemplateDescriptor:
    """The fields of a Word file; pass the ``checksum`` already computed for it."""

    checksum = checksum or hashlib.sha256(content).hexdigest()
    fields = inspect_docx_template_bytes(content, filename=filename)
    return FlowPackageTemplateDescriptor(
        filename=filename,
        checksum=checksum,
        size_bytes=len(content),
        fields=[
            FlowPackageTemplateField.model_validate(
                {"name": field["name"], "kind": field["kind"]}
            )
            for field in fields
        ],
        asset_path=f"templates/{checksum}.docx" if included else None,
    )


@dataclass(frozen=True, slots=True)
class _TemplateCandidate:
    ref: str
    filename: str
    content: bytes
    checksum: str
    expected: FlowPackageTemplateDescriptor
    included: bool


@dataclass(frozen=True, slots=True)
class _ResolvedTemplate:
    file: FlowPackageTemplateFile
    unpacked_bytes: int
    inspected: FlowPackageTemplateDescriptor


def resolve_flow_package_template_files(
    envelope: FlowPackageEnvelope,
    uploads: Sequence[FlowPackageTemplateUpload] = (),
) -> dict[str, FlowPackageTemplateFile]:
    """The Word file of every template slot, each slot keeping its own filename.

    The cheap bounds run first and refuse before any archive is expanded: the
    upload count, the encoded size of all uploads together, and the unpacked
    size summed over every slot (a file reused by many slots counts once per
    slot, since each becomes its own asset). Each payload is hashed once, its
    checksum carried from there on, and a file is inspected once however many
    slots use it.
    """

    requirements = {
        requirement.slot_ref.ref: requirement
        for requirement in envelope.requirements.requirements
        if isinstance(requirement, FlowPackageTemplateAssetRequirement)
        and requirement.template is not None
    }
    if len(uploads) > MAX_FLOW_AUTHORING_STEPS:
        raise _invalid_upload("Too many Word template uploads.")
    if sum(len(upload.content_base64) for upload in uploads) > (
        MAX_TEMPLATE_UPLOADS_BASE64_CHARS
    ):
        raise _invalid_upload("The Word template uploads exceed the size limit.")

    packaged = _packaged_templates(envelope, requirements)
    files = {ref: resolved.file for ref, resolved in packaged.items()}
    if not uploads:
        return files

    candidates: list[_TemplateCandidate] = []
    seen: set[str] = set()
    total_bytes = 0
    for upload in uploads:
        requirement = requirements.get(upload.template_ref)
        if (
            requirement is None
            or requirement.template is None
            or upload.template_ref in packaged
            or upload.template_ref in seen
        ):
            raise _invalid_upload(
                "The uploaded Word template does not match a missing package template.",
                upload.template_ref,
            )
        seen.add(upload.template_ref)
        try:
            content = base64.b64decode(upload.content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise _invalid_upload(
                "The Word template upload is not valid base64.", upload.template_ref
            ) from exc
        total_bytes += len(content)
        if total_bytes > MAX_FLOW_PACKAGE_BYTES:
            raise _invalid_upload(
                "The Word template uploads exceed the package size limit.",
                upload.template_ref,
            )
        candidates.append(
            _TemplateCandidate(
                ref=upload.template_ref,
                filename=upload.filename,
                content=content,
                checksum=hashlib.sha256(content).hexdigest(),
                expected=requirement.template,
                included=False,
            )
        )
    uploaded = _resolve_candidates(
        candidates,
        known=packaged.values(),
        spent=sum(resolved.unpacked_bytes for resolved in packaged.values()),
    )
    files.update({ref: resolved.file for ref, resolved in uploaded.items()})
    return files


def _packaged_templates(
    envelope: FlowPackageEnvelope,
    requirements: Mapping[str, FlowPackageTemplateAssetRequirement],
) -> dict[str, _ResolvedTemplate]:
    candidates: list[_TemplateCandidate] = []
    for ref, requirement in requirements.items():
        descriptor = requirement.template
        assert descriptor is not None
        if descriptor.asset_path is not None:
            candidates.append(
                _TemplateCandidate(
                    ref=ref,
                    filename=descriptor.filename,
                    content=envelope.template_payloads[descriptor.asset_path],
                    # Verified against these bytes when the envelope was built.
                    checksum=descriptor.checksum,
                    expected=descriptor,
                    included=True,
                )
            )
    return _resolve_candidates(candidates, known=(), spent=0)


def _resolve_candidates(
    candidates: Sequence[_TemplateCandidate],
    *,
    known: Iterable[_ResolvedTemplate],
    spent: int,
) -> dict[str, _ResolvedTemplate]:
    """Check every slot's filename, then the unpacked total, then each distinct file.

    ``known`` are files of the same request already checked, ``spent`` their
    unpacked total. Nothing is expanded until every slot has been counted.
    """

    unpacked = {item.file.checksum: item.unpacked_bytes for item in known}
    inspected = {item.file.checksum: item.inspected for item in known}
    total = spent
    for candidate in candidates:
        try:
            validate_template_filename(candidate.filename)
        except ValueError as exc:
            raise _invalid_upload(
                "The Word template filename is not valid.", candidate.ref
            ) from exc
        size = unpacked.get(candidate.checksum)
        if size is None:
            try:
                size = docx_template_archive_metrics(
                    candidate.content, filename=candidate.filename
                ).uncompressed_bytes
            except _TEMPLATE_ERRORS as exc:
                raise _invalid_upload(
                    "A Word template is not a supported DOCX file.", candidate.ref
                ) from exc
            unpacked[candidate.checksum] = size
        total += size
        if total > MAX_FLOW_PACKAGE_TEMPLATES_UNPACKED_BYTES:
            raise _invalid_upload(
                "The Word templates in this import are too large when unpacked.",
                candidate.ref,
            )

    resolved: dict[str, _ResolvedTemplate] = {}
    for candidate in candidates:
        actual = inspected.get(candidate.checksum)
        if actual is None:
            try:
                actual = inspect_package_template(
                    candidate.content,
                    filename=candidate.filename,
                    included=False,
                    checksum=candidate.checksum,
                )
            except _TEMPLATE_ERRORS as exc:
                raise _invalid_upload(
                    "A package Word template is not valid."
                    if candidate.included
                    else "The uploaded file is not a supported DOCX template.",
                    candidate.ref,
                ) from exc
            inspected[candidate.checksum] = actual
        require_package_template_fields(
            candidate.expected,
            actual.model_copy(update={"filename": candidate.filename}),
            slot_ref=candidate.ref,
        )
        resolved[candidate.ref] = _ResolvedTemplate(
            file=FlowPackageTemplateFile(
                filename=candidate.filename,
                content=candidate.content,
                checksum=candidate.checksum,
            ),
            unpacked_bytes=unpacked[candidate.checksum],
            inspected=actual,
        )
    return resolved


_TEMPLATE_ERRORS = (
    ValueError,
    RuntimeError,
    BadRequestException,
    FileNotSupportedException,
)


def _invalid_upload(message: str, slot_ref: str = "") -> FlowPackageValidationError:
    return FlowPackageValidationError(
        code=FlowPackageErrorCode.TEMPLATE_FILE_INVALID,
        message=message,
        context={"slot_ref": slot_ref},
    )
