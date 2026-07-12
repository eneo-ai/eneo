from __future__ import annotations

from eneo.flow_packages.application.flow_package_export_service import (
    MAX_PACKAGE_EXPORT_BYTES,
)
from eneo.flow_packages.domain.flow_package_errors import (
    FlowPackageErrorCode,
    FlowPackageExportErrorCode,
)
from eneo.flow_packages.infrastructure.flow_package_zip_reader import (
    MAX_PACKAGE_UPLOAD_BYTES,
)
from eneo.main.exceptions import ErrorCodes

IMPORT_PLAN_SCOPE_MISMATCH_MESSAGE = (
    "API key space scope does not match target package import space."
)

PACKAGE_VALIDATION_ERROR_EXAMPLES: dict[str, dict[str, object]] = {
    "zip_unsafe": {
        "summary": "Unsafe package zip",
        "value": {
            "message": "Flow package zip is not safe.",
            "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
            "code": "flow_package_zip_unsafe",
            "context": {"reason": "bad_zip"},
        },
    },
    "checksum_mismatch": {
        "summary": "Package checksum mismatch",
        "value": {
            "message": "Flow package checksum does not match its manifest.",
            "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
            "code": "flow_package_checksum_mismatch",
        },
    },
    "manifest_invalid": {
        "summary": "Manifest schema is invalid",
        "value": {
            "message": "Flow package manifest is invalid.",
            "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
            "code": "flow_package_manifest_invalid",
        },
    },
    "provenance_invalid": {
        "summary": "Package provenance schema is invalid",
        "value": {
            "message": "Flow package subdocument is invalid.",
            "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
            "code": FlowPackageErrorCode.PROVENANCE_INVALID.value,
        },
    },
    "schema_unsupported": {
        "summary": "Package schema version is unsupported",
        "value": {
            "message": "Unsupported Flow package schema version.",
            "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
            "code": "flow_package_schema_unsupported",
            "context": {"path": "manifest.json"},
        },
    },
    "package_kind_unsupported": {
        "summary": "Package kind is unsupported by Flow import",
        "value": {
            "message": "This package reader only supports flow package payloads.",
            "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
            "code": FlowPackageErrorCode.PACKAGE_KIND_UNSUPPORTED.value,
            "context": {
                "package_kind": "assistant",
                "payload_schema": "eneo.assistant_package.v1",
            },
        },
    },
    "local_resource_refs_not_portable": {
        "summary": "Package contains local resource references",
        "value": {
            "message": "Flow package contains local resource references.",
            "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
            "code": "flow_package_local_resource_refs_not_portable",
            "context": {"resource_ref": "11111111-1111-4111-8111-111111111111"},
        },
    },
    "undeclared_draft_ref": {
        "summary": "Draft references an undeclared package slot",
        "value": {
            "message": "Flow package draft references a resource slot that is not declared.",
            "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
            "code": FlowPackageErrorCode.IMPORT_DRAFT_REFERENCES_UNDECLARED_SLOT.value,
            "context": {"slot_ref": "model.missing", "unknown_count": 1},
        },
    },
    "requirements_usage_invalid": {
        "summary": "Package requirement does not match its draft use",
        "value": {
            "message": "Flow package resource requirements do not match draft usage.",
            "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
            "code": FlowPackageErrorCode.REQUIREMENTS_INVALID.value,
            "context": {
                "slot_ref": "model.speech",
                "reason": "assistant_model_requires_completion_model",
            },
        },
    },
    "portable_step_identity_invalid": {
        "summary": "Package step identity is not portable",
        "value": {
            "message": "Flow package step identity is not portable.",
            "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
            "code": FlowPackageErrorCode.FLOW_DRAFT_INVALID.value,
            "context": {
                "plan_step_ref": "extract",
                "reason": "existing_step_ref_not_portable",
            },
        },
    },
    "mcp_unsupported": {
        "summary": "Package contains unsupported MCP resources",
        "value": {
            "message": "Flow packages do not support MCP fields or resources.",
            "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
            "code": FlowPackageErrorCode.IMPORT_MCP_UNSUPPORTED.value,
            "context": {},
        },
    },
    "template_use_unsupported": {
        "summary": "Package draft uses an unsupported template asset",
        "value": {
            "message": (
                "Flow package import does not support template asset installation yet."
            ),
            "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
            "code": FlowPackageErrorCode.IMPORT_TEMPLATE_ASSETS_UNSUPPORTED.value,
            "context": {"plan_step_ref": "render-report"},
        },
    },
}

FLOW_PACKAGE_IMPORT_PLAN_BAD_REQUEST_EXAMPLES: dict[str, dict[str, object]] = {
    **PACKAGE_VALIDATION_ERROR_EXAMPLES,
    "flow_draft_invalid": {
        "summary": "Portable Flow graph is invalid",
        "value": {
            "message": "Flow package draft does not satisfy Flow graph rules.",
            "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
            "code": FlowPackageErrorCode.FLOW_DRAFT_INVALID.value,
            "context": {"reason": "duplicate_step_name"},
        },
    },
}

FLOW_PACKAGE_VALIDATE_FORBIDDEN_EXAMPLES: dict[str, dict[str, object]] = {
    "tenant_permission": {
        "summary": "Missing Flow authoring permission",
        "value": {
            "message": "You do not have permission to manage flows.",
            "eneo_error_code": int(ErrorCodes.UNAUTHORIZED),
            "code": "insufficient_tenant_permission",
            "context": {"auth_layer": "tenant_role"},
        },
    },
    "api_key_scope": {
        "summary": "API key must be tenant-scoped",
        "value": {
            "message": "This endpoint requires a tenant-scoped API key.",
            "eneo_error_code": int(ErrorCodes.UNAUTHORIZED),
            "code": "insufficient_scope",
            "context": {"auth_layer": "api_key_scope"},
        },
    },
}

FLOW_PACKAGE_IMPORT_PLAN_FORBIDDEN_EXAMPLES: dict[str, dict[str, object]] = {
    "tenant_permission": {
        "summary": "Missing Flow authoring permission",
        "value": {
            "message": "You do not have permission to manage flows.",
            "eneo_error_code": int(ErrorCodes.UNAUTHORIZED),
            "code": "insufficient_tenant_permission",
            "context": {"auth_layer": "tenant_role"},
        },
    },
    "api_key_scope": {
        "summary": "API key cannot access target space",
        "value": {
            "message": IMPORT_PLAN_SCOPE_MISMATCH_MESSAGE,
            "eneo_error_code": int(ErrorCodes.UNAUTHORIZED),
            "code": "insufficient_scope",
            "context": {"auth_layer": "api_key_scope"},
        },
    },
    "space_permission": {
        "summary": "Missing target-space Flow permission",
        "value": {
            "message": "You do not have permission to edit flows in this space.",
            "eneo_error_code": int(ErrorCodes.UNAUTHORIZED),
            "code": "insufficient_space_permission",
            "context": {"auth_layer": "space_membership"},
        },
    },
}

FLOW_PACKAGE_TOO_LARGE_EXAMPLE: dict[str, dict[str, object]] = {
    "file_too_large": {
        "summary": "Package upload exceeds the package byte cap",
        "value": {
            "message": "Flow package upload exceeds the allowed size.",
            "eneo_error_code": int(ErrorCodes.FILE_TOO_LARGE),
            "code": "flow_package_file_too_large",
            "context": {"max_package_upload_bytes": MAX_PACKAGE_UPLOAD_BYTES},
            "details": {
                "file_size_bytes": MAX_PACKAGE_UPLOAD_BYTES + 1,
                "file_size_human": "5.0 MB",
                "max_size_bytes": MAX_PACKAGE_UPLOAD_BYTES,
                "max_size_human": "5.0 MB",
            },
        },
    }
}

FLOW_PACKAGE_IMPORT_BAD_REQUEST_EXAMPLES: dict[str, dict[str, object]] = {
    **FLOW_PACKAGE_IMPORT_PLAN_BAD_REQUEST_EXAMPLES,
    "reviewed_plan_checksum_mismatch": {
        "summary": "Package no longer matches the reviewed import plan",
        "value": {
            "message": "Flow package does not match the reviewed import plan.",
            "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
            "code": FlowPackageErrorCode.CHECKSUM_MISMATCH.value,
            "context": {
                "expected_content_checksum": "0" * 64,
                "current_content_checksum": "1" * 64,
            },
        },
    },
    "base64_invalid": {
        "summary": "Package payload is not valid base64",
        "value": {
            "message": "Flow package payload is not valid base64.",
            "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
            "code": FlowPackageErrorCode.BASE64_INVALID.value,
        },
    },
    "unknown_binding": {
        "summary": "Selected package slot is not declared",
        "value": {
            "message": "Flow package import selected an undeclared resource slot.",
            "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
            "code": FlowPackageErrorCode.IMPORT_UNKNOWN_RESOURCE_BINDING.value,
            "context": {"slot_ref": "model.unknown", "unknown_count": 1},
        },
    },
    "missing_binding": {
        "summary": "Required knowledge slot has no local mapping",
        "value": {
            "message": "Flow package import is missing a required resource binding.",
            "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
            "code": FlowPackageErrorCode.IMPORT_MISSING_REQUIRED_RESOURCE_BINDING.value,
            "context": {"slot_ref": "knowledge.policy", "missing_count": 1},
        },
    },
    "unavailable_resource": {
        "summary": "Selected local resource is not available in the target space",
        "value": {
            "message": "Flow package import selected a resource that is not available in the target space.",
            "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
            "code": FlowPackageErrorCode.IMPORT_UNAVAILABLE_LOCAL_RESOURCE.value,
            "context": {
                "slot_ref": "model.structured",
                "local_kind": "completion_model",
                "local_id": "11111111-1111-4111-8111-111111111111",
            },
        },
    },
    "selected_model_ineligible": {
        "summary": "Selected model fails hard package requirements",
        "value": {
            "message": "Selected model does not satisfy the package slot's hard requirements.",
            "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
            "code": FlowPackageErrorCode.IMPORT_SELECTED_MODEL_INELIGIBLE.value,
            "context": {
                "slot_ref": "model.structured",
                "local_kind": "completion_model",
                "local_id": "11111111-1111-4111-8111-111111111111",
                "reason": "model_context_too_small",
                "reason_count": 1,
            },
        },
    },
    "target_transcription_model_changed": {
        "summary": "Target transcription default changed after planning",
        "value": {
            "message": (
                "The target space transcription model changed after import planning."
            ),
            "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
            "code": FlowPackageErrorCode.IMPORT_UNAVAILABLE_LOCAL_RESOURCE.value,
            "context": {
                "slot_ref": "model.flow_input_transcription",
                "local_kind": "transcription_model",
                "local_id": "11111111-1111-4111-8111-111111111111",
                "current_local_id": "22222222-2222-4222-8222-222222222222",
            },
        },
    },
    "template_assets_unsupported": {
        "summary": "Package contains template assets that cannot be installed yet",
        "value": {
            "message": "Flow package import does not support template asset installation yet.",
            "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
            "code": FlowPackageErrorCode.IMPORT_TEMPLATE_ASSETS_UNSUPPORTED.value,
            "context": {"slot_ref": "template_asset.report-template"},
        },
    },
    "duplicate_binding": {
        "summary": "Selected package slot has duplicate local mappings",
        "value": {
            "message": "Duplicate resource binding for slot 'model.structured'.",
            "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
            "code": "duplicate_slot_binding",
            "context": {
                "reason": "duplicate_slot_binding",
                "slot_ref": "model.structured",
                "expected_kind": "model",
            },
        },
    },
}

_FLOW_PACKAGE_EXPORT_BAD_REQUEST_MESSAGES = {
    FlowPackageExportErrorCode.MISSING_ASSISTANT_SNAPSHOT: (
        "Flow package export requires assistant authoring snapshots for every step."
    ),
    FlowPackageExportErrorCode.UNSUPPORTED_STEP_IO: (
        "Flow package export does not support this step input, output, or mode yet."
    ),
    FlowPackageExportErrorCode.STEP_CONFIG_NOT_PORTABLE: (
        "Flow package export found step configuration that cannot be exported safely; "
        "remove local credentials or unsupported configuration before exporting."
    ),
    FlowPackageExportErrorCode.UNMAPPED_RESOURCE_REF: (
        "Flow package export requires every local resource reference to be mapped to a package slot."
    ),
    FlowPackageExportErrorCode.DUPLICATE_RESOURCE_BINDING: (
        "Flow package export found duplicate package-slot mappings for a local resource."
    ),
    FlowPackageExportErrorCode.TEMPLATE_ASSET_PAYLOAD_UNSUPPORTED: (
        "Flow package export does not support portable template assets yet."
    ),
    FlowPackageExportErrorCode.VARIABLE_REFERENCE_INVALID: (
        "Flow package export found a prompt or contract variable that cannot be resolved portably."
    ),
    FlowPackageExportErrorCode.JSON_PAYLOAD_TOO_DEEP: (
        "Flow package export found a JSON payload that is too deeply nested."
    ),
    FlowPackageExportErrorCode.FORM_SCHEMA_INVALID: (
        "Flow package export requires a valid Flow form schema."
    ),
}

FLOW_PACKAGE_EXPORT_BAD_REQUEST_EXAMPLES: dict[str, dict[str, object]] = {
    code.name.casefold(): {
        "summary": code.value.removeprefix("flow_package_export_").replace("_", " "),
        "value": {
            "message": _FLOW_PACKAGE_EXPORT_BAD_REQUEST_MESSAGES[code],
            "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
            "code": code.value,
        },
    }
    for code in FlowPackageExportErrorCode
    if code is not FlowPackageExportErrorCode.PACKAGE_BYTES_TOO_LARGE
}

FLOW_PACKAGE_EXPORT_TOO_LARGE_EXAMPLE: dict[str, dict[str, object]] = {
    "package_too_large": {
        "summary": "Package export exceeds the package byte cap",
        "value": {
            "message": "Flow package export exceeds the allowed size.",
            "eneo_error_code": int(ErrorCodes.FILE_TOO_LARGE),
            "code": FlowPackageExportErrorCode.PACKAGE_BYTES_TOO_LARGE.value,
            "context": {"max_package_export_bytes": MAX_PACKAGE_EXPORT_BYTES},
            "details": {
                "file_size_bytes": MAX_PACKAGE_EXPORT_BYTES + 1,
                "file_size_human": "5.0 MB",
                "max_size_bytes": MAX_PACKAGE_EXPORT_BYTES,
                "max_size_human": "5.0 MB",
            },
        },
    }
}

FLOW_PACKAGE_EXPORT_FORBIDDEN_EXAMPLES: dict[str, dict[str, object]] = {
    "api_key_scope": {
        "summary": "API key cannot access the flow",
        "value": {
            "message": "API key does not have access to this flow.",
            "eneo_error_code": int(ErrorCodes.UNAUTHORIZED),
            "code": "insufficient_scope",
            "context": {"auth_layer": "api_key_scope"},
        },
    },
    "space_permission": {
        "summary": "Missing Flow edit permission",
        "value": {
            "message": "You do not have permission to edit flows in this space.",
            "eneo_error_code": int(ErrorCodes.UNAUTHORIZED),
            "code": "insufficient_space_permission",
            "context": {"auth_layer": "space_membership"},
        },
    },
    "flow_owner": {
        "summary": "Draft owner permission required",
        "value": {
            "message": "You do not have permission to modify another member's draft flow.",
            "eneo_error_code": int(ErrorCodes.UNAUTHORIZED),
            "code": "flow_owner_required",
            "context": {"auth_layer": "flow_owner"},
        },
    },
}


def flow_package_binary_response(media_type: str) -> dict[str, object]:
    return {
        "description": "Portable Flow package bundle.",
        "content": {
            media_type: {
                "schema": {"type": "string", "format": "binary"},
                "example": "PK...binary .eneo-flowpkg zip payload...",
            }
        },
    }
