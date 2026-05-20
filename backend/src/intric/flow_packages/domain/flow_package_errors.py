from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

FlowPackageErrorContextValue = str | int
FlowPackageErrorContext = Mapping[str, FlowPackageErrorContextValue]


class FlowPackageErrorCode(StrEnum):
    BASE64_INVALID = "flow_package_base64_invalid"
    ZIP_UNSAFE = "flow_package_zip_unsafe"
    MANIFEST_INVALID = "flow_package_manifest_invalid"
    REQUIREMENTS_INVALID = "flow_package_requirements_invalid"
    FLOW_DRAFT_INVALID = "flow_package_flow_draft_invalid"
    PROVENANCE_INVALID = "flow_package_provenance_invalid"
    SCHEMA_UNSUPPORTED = "flow_package_schema_unsupported"
    PACKAGE_KIND_UNSUPPORTED = "flow_package_kind_unsupported"
    CHECKSUM_MISMATCH = "flow_package_checksum_mismatch"
    LOCAL_RESOURCE_REFS_NOT_PORTABLE = "flow_package_local_resource_refs_not_portable"
    IMPORT_DRAFT_REFERENCES_UNDECLARED_SLOT = (
        "flow_package_import_draft_references_undeclared_slot"
    )
    IMPORT_UNKNOWN_RESOURCE_BINDING = "flow_package_import_unknown_resource_binding"
    IMPORT_MISSING_REQUIRED_RESOURCE_BINDING = (
        "flow_package_import_missing_required_resource_binding"
    )
    IMPORT_UNAVAILABLE_LOCAL_RESOURCE = "flow_package_import_unavailable_local_resource"
    IMPORT_SELECTED_MODEL_INELIGIBLE = "flow_package_import_selected_model_ineligible"
    IMPORT_MCP_UNSUPPORTED = "flow_package_import_mcp_unsupported"
    IMPORT_TEMPLATE_ASSETS_UNSUPPORTED = (
        "flow_package_import_template_assets_unsupported"
    )


class FlowPackageExportErrorCode(StrEnum):
    MISSING_ASSISTANT_SNAPSHOT = "flow_package_export_missing_assistant_snapshot"
    UNSUPPORTED_STEP_IO = "flow_package_export_unsupported_step_io"
    UNMAPPED_RESOURCE_REF = "flow_package_export_unmapped_resource_ref"
    DUPLICATE_RESOURCE_BINDING = "flow_package_export_duplicate_resource_binding"
    MCP_EXPORT_UNSUPPORTED = "flow_package_export_mcp_unsupported"
    TEMPLATE_ASSET_PAYLOAD_UNSUPPORTED = (
        "flow_package_export_template_asset_payload_unsupported"
    )
    VARIABLE_REFERENCE_INVALID = "flow_package_export_variable_reference_invalid"
    JSON_PAYLOAD_TOO_DEEP = "flow_package_export_json_payload_too_deep"
    FORM_SCHEMA_INVALID = "flow_package_export_form_schema_invalid"
    PACKAGE_BYTES_TOO_LARGE = "flow_package_export_too_large"


class FlowPackageZipUnsafeReason(StrEnum):
    BAD_ZIP = "bad_zip"
    TOO_MANY_ENTRIES = "too_many_entries"
    DIRECTORY_ENTRY = "directory_entry"
    SYMLINK_ENTRY = "symlink_entry"
    ABSOLUTE_PATH = "absolute_path"
    PATH_TRAVERSAL = "path_traversal"
    BACKSLASH_PATH = "backslash_path"
    UNKNOWN_ENTRY = "unknown_entry"
    DUPLICATE_ENTRY = "duplicate_entry"
    MISSING_REQUIRED_ENTRY = "missing_required_entry"
    COMPRESSED_ENTRY_TOO_LARGE = "compressed_entry_too_large"
    UNCOMPRESSED_ENTRY_TOO_LARGE = "uncompressed_entry_too_large"
    TOTAL_UNCOMPRESSED_TOO_LARGE = "total_uncompressed_too_large"
    DECOMPRESSION_RATIO_TOO_HIGH = "decompression_ratio_too_high"
    JSON_TOO_LARGE = "json_too_large"


class FlowPackageValidationError(ValueError):
    def __init__(
        self,
        *,
        code: FlowPackageErrorCode,
        message: str,
        context: FlowPackageErrorContext | None = None,
    ) -> None:
        self.code = code
        self.context = dict(context or {})
        super().__init__(message)


class FlowPackageExportError(ValueError):
    def __init__(
        self,
        *,
        code: FlowPackageExportErrorCode,
        message: str,
        context: FlowPackageErrorContext | None = None,
    ) -> None:
        self.code = code
        self.context = dict(context or {})
        super().__init__(message)
