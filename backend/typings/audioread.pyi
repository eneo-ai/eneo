from collections.abc import Iterator
from typing import Self

class AudioFile(Iterator[bytes]):
    samplerate: int
    channels: int

    def __enter__(self) -> Self: ...

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None: ...

    def __iter__(self) -> Iterator[bytes]: ...

    def __next__(self) -> bytes: ...


def audio_open(filepath: str) -> AudioFile: ...

