"""A request that names a File the caller can no longer send is refused."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.files.file_service import require_requested_files
from eneo.main.exceptions import BadRequestException


def test_passes_when_every_requested_file_was_found() -> None:
    first, second = uuid4(), uuid4()
    files = [SimpleNamespace(id=first), SimpleNamespace(id=second)]

    require_requested_files([first, second, first], files)
    require_requested_files([], [])


def test_names_the_missing_file() -> None:
    present, missing = uuid4(), uuid4()

    with pytest.raises(BadRequestException) as excinfo:
        require_requested_files([present, missing], [SimpleNamespace(id=present)])

    assert str(excinfo.value) == (
        f"The attached file is no longer available: {missing}. Upload it again."
    )


def test_lists_every_missing_file_once_in_request_order() -> None:
    first, second = uuid4(), uuid4()

    with pytest.raises(BadRequestException) as excinfo:
        require_requested_files([first, second, first], [])

    assert str(excinfo.value) == (
        f"The attached files are no longer available: {first}, {second}. "
        "Upload them again."
    )
