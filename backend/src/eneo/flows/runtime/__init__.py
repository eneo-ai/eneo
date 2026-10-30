from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "PlatformFlowExecutionBackend": (
        "eneo.flows.runtime.platform_execution_backend",
        "PlatformFlowExecutionBackend",
    ),
    "rag_retrieval": ("eneo.flows.runtime.rag_retrieval", None),
    "step_execution_runtime": ("eneo.flows.runtime.step_execution_runtime", None),
    "transcription_runtime": ("eneo.flows.runtime.transcription_runtime", None),
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
