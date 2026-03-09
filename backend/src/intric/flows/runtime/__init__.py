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
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str):
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
