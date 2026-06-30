from __future__ import annotations

import io
import pickle
from typing import cast

LEGACY_PACKAGE = "intric"
CURRENT_PACKAGE = "eneo"


class RenamedPackageUnpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str) -> object:
        if module == LEGACY_PACKAGE or module.startswith(f"{LEGACY_PACKAGE}."):
            module = CURRENT_PACKAGE + module[len(LEGACY_PACKAGE) :]
        return super().find_class(module, name)


def serialize_job(data: dict[str, object]) -> bytes:
    return pickle.dumps(data)


def deserialize_job(payload: bytes) -> dict[str, object]:
    data = RenamedPackageUnpickler(io.BytesIO(payload)).load()
    if not isinstance(data, dict):
        raise TypeError("ARQ job payload must deserialize to a dictionary")

    job: dict[str, object] = {}
    for key, value in cast(dict[object, object], data).items():
        if not isinstance(key, str):
            raise TypeError("ARQ job payload keys must be strings")
        job[key] = value
    return job
