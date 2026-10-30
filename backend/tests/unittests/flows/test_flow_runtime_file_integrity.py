"""Constraint names are read the way SQLAlchemy's asyncpg adapter presents them.

The adapter wraps the driver error (``translated_error from error``), so the
violated constraint is named on ``exc.orig.__cause__``; the wrapper's message
does not carry it.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from eneo.flows.flow_runtime_file_integrity import (
    RUNTIME_FILE_ATTACHMENT_CONSTRAINT_NAMES,
    RUNTIME_UPLOAD_BINDING_CONSTRAINT,
    constraint_name_from_integrity_error,
    is_runtime_file_attachment_integrity_error,
    is_runtime_upload_binding_integrity_error,
)
from eneo.flows.infrastructure.flow_repo import _is_active_flow_name_violation


class _DriverError(Exception):
    def __init__(self, constraint_name: str):
        super().__init__("driver error")
        self.constraint_name = constraint_name


def _asyncpg_shaped_error(constraint_name: str) -> IntegrityError:
    wrapper = Exception(
        "<class 'asyncpg.exceptions.IntegrityConstraintViolationError'>"
    )
    wrapper.__cause__ = _DriverError(constraint_name)
    return IntegrityError(statement="INSERT", params={}, orig=wrapper)


def test_binding_violation_is_read_from_the_driver_error_cause() -> None:
    exc = _asyncpg_shaped_error(RUNTIME_UPLOAD_BINDING_CONSTRAINT)

    assert (
        constraint_name_from_integrity_error(exc) == RUNTIME_UPLOAD_BINDING_CONSTRAINT
    )
    assert is_runtime_upload_binding_integrity_error(exc)


@pytest.mark.parametrize("name", sorted(RUNTIME_FILE_ATTACHMENT_CONSTRAINT_NAMES))
def test_attachment_violation_is_read_from_the_driver_error_cause(name: str) -> None:
    assert is_runtime_file_attachment_integrity_error(_asyncpg_shaped_error(name))


def test_active_flow_name_violation_is_read_from_the_driver_error_cause() -> None:
    assert _is_active_flow_name_violation(
        _asyncpg_shaped_error("uq_flows_space_id_name_active")
    )
    assert not _is_active_flow_name_violation(_asyncpg_shaped_error("other"))


def test_a_constraint_name_only_in_the_message_is_not_a_classification() -> None:
    exc = IntegrityError(
        statement="DELETE",
        params={},
        orig=Exception(f'violates "{RUNTIME_UPLOAD_BINDING_CONSTRAINT}"'),
    )

    assert constraint_name_from_integrity_error(exc) is None
    assert not is_runtime_upload_binding_integrity_error(exc)
    assert not _is_active_flow_name_violation(exc)
