"""Flow compatibility names for shared resource-package provenance."""

from eneo.resource_packages.provenance import (
    ResourcePackageOmission,
    ResourcePackageOmissionKind,
    ResourcePackageProvenance,
)

FlowPackageOmissionKind = ResourcePackageOmissionKind
FlowPackageOmission = ResourcePackageOmission
FlowPackageProvenance = ResourcePackageProvenance

__all__ = [
    "FlowPackageOmission",
    "FlowPackageOmissionKind",
    "FlowPackageProvenance",
]
