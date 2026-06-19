from __future__ import annotations

from sqlalchemy.exc import IntegrityError

RUNTIME_UPLOAD_BINDING_CONSTRAINT = "fk_flow_run_step_input_files_runtime_upload"

RUNTIME_FILE_ATTACHMENT_CONSTRAINT_NAMES = frozenset(
    {
        "fk_flow_run_step_input_files_file_id_files",
        # Delete-time attachment detection intentionally includes the binding FK:
        # deleting the file cascades to the runtime upload row before this FK rejects it.
        RUNTIME_UPLOAD_BINDING_CONSTRAINT,
        "fk_flow_run_step_result_files_file_id_files",
    }
)


def _constraint_name_from_object(value: object) -> str | None:
    diagnostic = getattr(value, "diag", None)
    constraint_name = getattr(diagnostic, "constraint_name", None)
    if isinstance(constraint_name, str):
        return constraint_name
    constraint_name = getattr(value, "constraint_name", None)
    if isinstance(constraint_name, str):
        return constraint_name
    return None


def _known_constraint_name_from_message(value: object) -> str | None:
    message = str(value)
    return next(
        (
            constraint_name
            for constraint_name in RUNTIME_FILE_ATTACHMENT_CONSTRAINT_NAMES
            if constraint_name in message
        ),
        None,
    )


def constraint_name_from_integrity_error(exc: IntegrityError) -> str | None:
    return _constraint_name_from_object(
        exc.orig
    ) or _known_constraint_name_from_message(exc.orig)


def is_runtime_file_attachment_integrity_error(exc: IntegrityError) -> bool:
    """Classify constraints showing a runtime file is still bound to a run."""
    constraint_name = constraint_name_from_integrity_error(exc)
    return constraint_name in RUNTIME_FILE_ATTACHMENT_CONSTRAINT_NAMES


def is_runtime_upload_binding_integrity_error(exc: IntegrityError) -> bool:
    """Classify a step-input insert that raced a runtime upload deletion."""
    return (
        constraint_name_from_integrity_error(exc) == RUNTIME_UPLOAD_BINDING_CONSTRAINT
    )
