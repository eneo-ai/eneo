from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eneo.flows.flow_resource_bindings import LocalResourceBinding
from eneo.resource_packages.import_record import (
    ResourcePackageImportFailurePayload,
    ResourcePackageImportSource,
    ResourcePackageImportStatus,
)

FlowPackageImportSource = ResourcePackageImportSource
FlowPackageImportStatus = ResourcePackageImportStatus
FlowPackageImportFailurePayload = ResourcePackageImportFailurePayload


def _empty_bindings() -> list[LocalResourceBinding]:
    return []


class FlowPackageImportSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    selected_bindings: list[LocalResourceBinding] = Field(
        default_factory=_empty_bindings,
        description="Local target resources selected for package dependency slots.",
    )

    def bindings_tuple(self) -> tuple[LocalResourceBinding, ...]:
        return tuple(self.selected_bindings)

    def storage_json(self) -> dict[str, object]:
        return self.model_dump(
            mode="json",
            exclude={
                "selected_bindings": {
                    "__all__": {"slot_ref": {"ref"}},
                }
            },
        )

    @model_validator(mode="after")
    def canonicalize_binding_order(self) -> "FlowPackageImportSelection":
        self.selected_bindings = sorted(
            self.selected_bindings,
            key=lambda binding: (
                binding.slot_ref.ref,
                binding.local_kind.value,
                str(binding.local_id),
            ),
        )
        return self
