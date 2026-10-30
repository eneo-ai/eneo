from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

from eneo.resource_packages.manifest import EneoPackageKind

ResourceT = TypeVar("ResourceT", contravariant=True)
PayloadT = TypeVar("PayloadT", bound=BaseModel)
BindingsT = TypeVar("BindingsT", contravariant=True)
InstallT = TypeVar("InstallT", covariant=True)


class ResourcePackageAdapter(Protocol[ResourceT, PayloadT, BindingsT, InstallT]):
    """Contract owned by each resource kind using the shared package core."""

    kind: EneoPackageKind
    payload_schema: str

    def export_payload(self, resource: ResourceT) -> PayloadT: ...

    def prepare_import(self, payload: PayloadT, bindings: BindingsT) -> InstallT: ...
