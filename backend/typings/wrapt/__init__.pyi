from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., object])


def decorator(func: F | None = None) -> Any: ...

