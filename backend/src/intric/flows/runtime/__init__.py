from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "CeleryFlowExecutionBackend": (
        "intric.flows.runtime.celery_execution_backend",
        "CeleryFlowExecutionBackend",
    ),
    "FLOW_EXECUTE_TASK_NAME": (
        "intric.flows.runtime.celery_execution_backend",
        "FLOW_EXECUTE_TASK_NAME",
    ),
    "celery_app": ("intric.flows.runtime.celery_app", "celery_app"),
    "create_flow_celery_app": (
        "intric.flows.runtime.celery_app",
        "create_flow_celery_app",
    ),
    "rag_retrieval": ("intric.flows.runtime.rag_retrieval", None),
    "step_execution_runtime": ("intric.flows.runtime.step_execution_runtime", None),
    "transcription_runtime": ("intric.flows.runtime.transcription_runtime", None),
}


def __getattr__(name: str):
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module = import_module(module_name)
    value = module if attr_name is None else getattr(module, attr_name)
    globals()[name] = value
    return value
