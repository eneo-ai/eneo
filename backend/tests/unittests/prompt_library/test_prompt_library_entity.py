from datetime import datetime, timezone
from uuid import uuid4

import pytest

from eneo.main.exceptions import BadRequestException
from eneo.prompt_library.domain.prompt_library import PromptLibraryEntry


def _entry() -> PromptLibraryEntry:
    return PromptLibraryEntry(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Standard",
        description="desc",
        text="You are a helpful assistant.",
        current_version=1,
        created_by_user_id=uuid4(),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def test_update_changes_name():
    e = _entry()
    e.update(name="Renamed")
    assert e.name == "Renamed"


def test_update_rejects_blank_name():
    e = _entry()
    with pytest.raises(BadRequestException):
        e.update(name="   ")


def test_update_clears_description_when_set_to_none_explicitly():
    e = _entry()
    e.update(description=None)
    assert e.description is None


def test_update_leaves_description_untouched_when_not_provided():
    e = _entry()
    original = e.description
    # NOT_PROVIDED is the default sentinel
    e.update(name="X")
    assert e.description == original


def test_update_changes_text():
    e = _entry()
    e.update(text="New text")
    assert e.text == "New text"


def test_update_rejects_blank_text():
    e = _entry()
    with pytest.raises(BadRequestException):
        e.update(text="  \n  ")
