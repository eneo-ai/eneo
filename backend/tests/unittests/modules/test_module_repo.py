from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import IntegrityError

from eneo.main.exceptions import NameCollisionException
from eneo.modules.module import ModuleCreate
from eneo.modules.module_repo import ModuleRepository


def integrity_error(*, constraint_name: str | None = None) -> IntegrityError:
    original = SimpleNamespace(constraint_name=constraint_name)
    return IntegrityError("INSERT INTO modules ...", {}, original)


async def test_add_translates_the_module_name_unique_constraint() -> None:
    repository = ModuleRepository(AsyncMock())
    repository.delegate.add = AsyncMock(
        side_effect=integrity_error(constraint_name="modules_unique")
    )

    with pytest.raises(NameCollisionException, match="tal-till-text"):
        await repository.add(ModuleCreate(name="tal-till-text"))


async def test_add_preserves_unrelated_integrity_failures() -> None:
    error = integrity_error(constraint_name="some_other_constraint")
    repository = ModuleRepository(AsyncMock())
    repository.delegate.add = AsyncMock(side_effect=error)

    with pytest.raises(IntegrityError) as raised:
        await repository.add(ModuleCreate(name="tal-till-text"))

    assert raised.value is error


async def test_add_recognizes_postgres_constraint_text_fallback() -> None:
    error = IntegrityError(
        "INSERT INTO modules ...",
        {},
        Exception('duplicate key value violates unique constraint "modules_unique"'),
    )
    repository = ModuleRepository(AsyncMock())
    repository.delegate.add = AsyncMock(side_effect=error)

    with pytest.raises(NameCollisionException):
        await repository.add(ModuleCreate(name="tal-till-text"))
