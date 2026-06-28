from collections.abc import Iterable
from typing import Any, Callable

class _StringMethods:
    def replace(self, pat: str, repl: str) -> _StringMethods: ...

    def cat(self, sep: str = "") -> str: ...


class Index:
    str: _StringMethods

    def astype(self, dtype: type[Any]) -> Index: ...


class Series:
    str: _StringMethods

    def items(self) -> Iterable[tuple[Any, Any]]: ...


class DataFrame:
    @property
    def empty(self) -> bool: ...

    @property
    def columns(self) -> Index: ...

    @columns.setter
    def columns(self, value: object) -> None: ...

    def ffill(self) -> DataFrame: ...

    def apply(self, func: Callable[[Series], Any], axis: int = ...) -> Series: ...

    def to_csv(self, index: bool = ..., sep: str = ...) -> str: ...


class ExcelFile:
    sheet_names: list[str]

    def __init__(self, path: Any, engine: str | None = ...) -> None: ...


def read_excel(
    io: Any,
    sheet_name: str | None = ...,
    engine: str | None = ...,
) -> DataFrame: ...


def notna(value: Any) -> bool: ...
