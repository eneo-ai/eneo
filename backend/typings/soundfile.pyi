from collections.abc import Iterator
from pathlib import Path
from typing import Any

class _Info:
    samplerate: int
    channels: int
    duration: float


class SoundFile:
    def __init__(
        self,
        file: Any,
        mode: str = ...,
        samplerate: int | None = ...,
        channels: int | None = ...,
        format: str | None = ...,
    ) -> None: ...

    def write(self, data: Any) -> None: ...

    def flush(self) -> None: ...


def info(file: str | Path) -> _Info: ...


def blocks(path: str | Path, blocksize: int) -> Iterator[Any]: ...

