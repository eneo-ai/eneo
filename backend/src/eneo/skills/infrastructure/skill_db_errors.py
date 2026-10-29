from sqlalchemy.exc import DBAPIError, IntegrityError

_LOCK_NOT_AVAILABLE_SQLSTATE = "55P03"


def is_constraint_violation(error: IntegrityError, constraint_name: str) -> bool:
    original = getattr(error, "orig", None)
    reported_name = getattr(original, "constraint_name", None)
    if reported_name == constraint_name:
        return True
    return constraint_name in str(original if original is not None else error)


def is_lock_not_available(error: DBAPIError) -> bool:
    orig = error.orig
    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    return sqlstate == _LOCK_NOT_AVAILABLE_SQLSTATE or (
        _LOCK_NOT_AVAILABLE_SQLSTATE in str(orig)
    )
