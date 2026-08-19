"""Flow compatibility names for shared resource-package manifests."""

from eneo.resource_packages.manifest import (
    APP_PACKAGE_PAYLOAD_SCHEMA,
    ASSISTANT_PACKAGE_PAYLOAD_SCHEMA,
    FLOW_PACKAGE_PAYLOAD_SCHEMA,
    MAX_RESOURCE_PACKAGE_VERSION_LENGTH,
    PACKAGE_PAYLOAD_SCHEMA_BY_KIND,
    EneoPackageKind,
    ResourcePackageManifest,
    ResourcePackageManifestMetadata,
    ResourcePackageManifestMetadataFields,
    resource_package_filename,
)

MAX_FLOW_PACKAGE_VERSION_LENGTH = MAX_RESOURCE_PACKAGE_VERSION_LENGTH
FlowPackageManifestMetadataFields = ResourcePackageManifestMetadataFields
FlowPackageManifestMetadata = ResourcePackageManifestMetadata
FlowPackageManifest = ResourcePackageManifest
flow_package_filename = resource_package_filename

__all__ = [
    "APP_PACKAGE_PAYLOAD_SCHEMA",
    "ASSISTANT_PACKAGE_PAYLOAD_SCHEMA",
    "EneoPackageKind",
    "FLOW_PACKAGE_PAYLOAD_SCHEMA",
    "FlowPackageManifest",
    "FlowPackageManifestMetadata",
    "FlowPackageManifestMetadataFields",
    "MAX_FLOW_PACKAGE_VERSION_LENGTH",
    "PACKAGE_PAYLOAD_SCHEMA_BY_KIND",
    "flow_package_filename",
]
