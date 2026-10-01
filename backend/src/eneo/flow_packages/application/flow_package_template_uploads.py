from __future__ import annotations

import base64
import binascii
import hashlib
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from eneo.flow_packages.domain.flow_package_envelope import FlowPackageEnvelope
from eneo.flow_packages.domain.flow_package_errors import (
    FlowPackageErrorCode,
    FlowPackageValidationError,
)
from eneo.flow_packages.domain.flow_package_limits import MAX_FLOW_PACKAGE_BYTES
from eneo.flow_packages.domain.flow_package_requirements import (
    FlowPackageTemplateAssetRequirement,
)
from eneo.flow_packages.domain.flow_package_templates import (
    FlowPackageTemplateDescriptor,
    FlowPackageTemplateField,
    FlowPackageTemplateFile,
    require_package_template_fields,
)
from eneo.flows.flow_authoring_spec import MAX_FLOW_AUTHORING_STEPS
from eneo.flows.runtime.docx_template_runtime import inspect_docx_template_bytes
from eneo.main.exceptions import BadRequestException

MAX_TEMPLATE_UPLOADS_JSON_BYTES = ((MAX_FLOW_PACKAGE_BYTES + 2) // 3) * 4 + 256 * 1024


class FlowPackageTemplateUpload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    template_ref: str = Field(min_length=1, max_length=255)
    filename: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(
        min_length=1, max_length=((MAX_FLOW_PACKAGE_BYTES + 2) // 3) * 4
    )


def inspect_package_template(
    content: bytes,
    *,
    filename: str,
    included: bool,
) -> FlowPackageTemplateDescriptor:
    checksum = hashlib.sha256(content).hexdigest()
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


def resolve_flow_package_template_files(
    envelope: FlowPackageEnvelope,
    uploads: Sequence[FlowPackageTemplateUpload] = (),
) -> dict[str, FlowPackageTemplateFile]:
    requirements = {
        requirement.slot_ref.ref: requirement
        for requirement in envelope.requirements.requirements
        if isinstance(requirement, FlowPackageTemplateAssetRequirement)
        and requirement.template is not None
    }
    files: dict[str, FlowPackageTemplateFile] = {}
    inspected: dict[str, FlowPackageTemplateDescriptor] = {}
    for ref, requirement in requirements.items():
        descriptor = requirement.template
        assert descriptor is not None
        if descriptor.asset_path is not None:
            actual = inspected.get(descriptor.asset_path)
            if actual is None:
                try:
                    actual = inspect_package_template(
                        envelope.template_payloads[descriptor.asset_path],
                        filename=descriptor.filename,
                        included=True,
                    )
                except (ValueError, RuntimeError, BadRequestException) as exc:
                    raise _invalid_upload(
                        "A package Word template is not valid.", ref
                    ) from exc
                inspected[descriptor.asset_path] = actual
            require_package_template_fields(descriptor, actual, slot_ref=ref)
            files[ref] = FlowPackageTemplateFile(
                filename=descriptor.filename,
                content=envelope.template_payloads[descriptor.asset_path],
                checksum=descriptor.checksum,
            )
    if len(uploads) > MAX_FLOW_AUTHORING_STEPS:
        raise _invalid_upload("Too many Word template uploads.")
    seen: set[str] = set()
    total_bytes = 0
    for upload in uploads:
        requirement = requirements.get(upload.template_ref)
        if (
            requirement is None
            or requirement.template is None
            or upload.template_ref in files
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
        try:
            descriptor = inspect_package_template(
                content, filename=upload.filename, included=False
            )
        except (ValueError, RuntimeError, BadRequestException) as exc:
            raise _invalid_upload(
                "The uploaded file is not a supported DOCX template.",
                upload.template_ref,
            ) from exc
        require_package_template_fields(
            requirement.template, descriptor, slot_ref=upload.template_ref
        )
        files[upload.template_ref] = FlowPackageTemplateFile(
            filename=descriptor.filename, content=content, checksum=descriptor.checksum
        )
    return files


def _invalid_upload(message: str, slot_ref: str = "") -> FlowPackageValidationError:
    return FlowPackageValidationError(
        code=FlowPackageErrorCode.TEMPLATE_FILE_INVALID,
        message=message,
        context={"slot_ref": slot_ref},
    )
