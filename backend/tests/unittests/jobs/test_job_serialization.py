from __future__ import annotations

import pickle
import sys
from types import ModuleType
from uuid import uuid4

from eneo.jobs.job_models import Task
from eneo.jobs.job_serialization import deserialize_job, serialize_job
from eneo.jobs.task_models import UploadInfoBlob


def _install_module(name: str) -> ModuleType:
    module = ModuleType(name)
    sys.modules[name] = module
    return module


def test_job_serializer_round_trips_current_payload() -> None:
    payload = {
        "t": None,
        "f": Task.UPLOAD_FILE,
        "a": (),
        "k": {},
        "et": 0,
    }

    assert deserialize_job(serialize_job(payload)) == payload


def test_job_deserializer_remaps_pre_rename_package_payloads() -> None:
    params = UploadInfoBlob(
        user_id=uuid4(),
        group_id=uuid4(),
        space_id=uuid4(),
        filepath="/tmp/document.txt",
        filename="document.txt",
        mimetype="text/plain",
    )

    module_names = (
        "intric",
        "intric.jobs",
        "intric.jobs.job_models",
        "intric.jobs.task_models",
    )
    previous_modules = {name: sys.modules.get(name) for name in module_names}
    previous_task_module = Task.__module__
    previous_params_module = UploadInfoBlob.__module__

    try:
        _install_module("intric")
        _install_module("intric.jobs")
        job_models = _install_module("intric.jobs.job_models")
        task_models = _install_module("intric.jobs.task_models")
        Task.__module__ = "intric.jobs.job_models"
        UploadInfoBlob.__module__ = "intric.jobs.task_models"
        job_models.Task = Task
        task_models.UploadInfoBlob = UploadInfoBlob

        encoded = pickle.dumps(
            {
                "t": 1,
                "f": Task.UPLOAD_FILE,
                "a": (params,),
                "k": {},
                "et": 0,
            }
        )
    finally:
        Task.__module__ = previous_task_module
        UploadInfoBlob.__module__ = previous_params_module
        for name, module in previous_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    decoded = deserialize_job(encoded)

    assert decoded["f"] is Task.UPLOAD_FILE
    args = decoded["a"]
    assert isinstance(args, tuple)
    decoded_params = args[0]
    assert isinstance(decoded_params, UploadInfoBlob)
    assert decoded_params.__class__.__module__ == "eneo.jobs.task_models"
