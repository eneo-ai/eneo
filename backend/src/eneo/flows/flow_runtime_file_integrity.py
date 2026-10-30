from __future__ import annotations

from sqlalchemy.exc import IntegrityError

RUNTIME_UPLOAD_BINDING_CONSTRAINT = "fk_flow_run_step_input_files_runtime_upload"
RUNTIME_STEP_INPUT_FILE_ATTACHMENT_CONSTRAINT = "flow_run_step_input_files_file_id_fkey"

RUNTIME_FILE_ATTACHMENT_CONSTRAINT_NAMES = frozenset(
    {
        RUNTIME_STEP_INPUT_FILE_ATTACHMENT_CONSTRAINT,
        # Delete-time attachment detection intentionally includes the binding FK:
        # deleting the file cascades to the runtime upload row before this FK rejects it.
        RUNTIME_UPLOAD_BINDING_CONSTRAINT,
        "fk_flow_run_step_result_files_file_tenant",
    }
)


def constraint_name_from_integrity_error(exc: IntegrityError) -> str | None:
    """Name the violated constraint the way SQLAlchemy's asyncpg adapter reports it.

    The adapter wraps the driver error (``translated_error from error``): the
    wrapper in ``exc.orig`` carries only the SQLSTATE, and asyncpg's own error
    in ``exc.orig.__cause__`` names the constraint.
    """
    driver_error = exc.orig.__cause__ if exc.orig is not None else None
    constraint_name = getattr(driver_error, "constraint_name", None)
    return constraint_name if isinstance(constraint_name, str) else None


def is_runtime_file_attachment_integrity_error(exc: IntegrityError) -> bool:
    """Classify constraints showing a runtime file is still bound to a run."""
    constraint_name = constraint_name_from_integrity_error(exc)
    return constraint_name in RUNTIME_FILE_ATTACHMENT_CONSTRAINT_NAMES


def is_runtime_upload_binding_integrity_error(exc: IntegrityError) -> bool:
    """Classify a step-input insert that raced a runtime upload deletion."""
    return (
        constraint_name_from_integrity_error(exc) == RUNTIME_UPLOAD_BINDING_CONSTRAINT
    )
