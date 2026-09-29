"""Environment variables that Eneo no longer reads.

Settings accepts unknown variables without complaint, so a deployment that
still sets one of these would otherwise lose the value without any sign.
"""

import logging
import sys
from collections.abc import Mapping
from dataclasses import dataclass

UPGRADE_GUIDE_URL = "https://docs.eneo.ai/v2.2/guides/upgrade-2-2-0"


@dataclass(frozen=True)
class RemovedVariable:
    name: str
    replacement: str | None = None
    note: str = ""


_MODULES_PERMISSION_NOTE = (
    "Module administration uses the `modules` permission instead."
)

REMOVED_VARIABLES: tuple[RemovedVariable, ...] = (
    RemovedVariable("INTRIC_SUPER_API_KEY", replacement="ENEO_SUPER_API_KEY"),
    RemovedVariable("INTRIC_SUPER_DUPER_API_KEY", note=_MODULES_PERMISSION_NOTE),
    RemovedVariable("ENEO_SUPER_DUPER_API_KEY", note=_MODULES_PERMISSION_NOTE),
)


def _is_set(
    name: str, environ: Mapping[str, str], values: Mapping[str, object]
) -> bool:
    # Settings matches names case-insensitively, and a value from an env file
    # reaches the validator as a lower-case key instead of through os.environ.
    lowered = name.lower()
    if any(key.lower() == lowered and value.strip() for key, value in environ.items()):
        return True
    value = values.get(lowered)
    return isinstance(value, str) and bool(value.strip())


def check_removed_variables(
    environ: Mapping[str, str], values: Mapping[str, object]
) -> None:
    """Log every removed variable that is still set.

    Exits when a renamed variable is set without its replacement: the value
    would be lost, and the failure would otherwise surface far from its cause
    (a bare 401 on every sysadmin call).
    """
    blocking: list[str] = []
    for variable in REMOVED_VARIABLES:
        if not _is_set(variable.name, environ, values):
            continue
        if variable.replacement is None:
            logging.error(
                "%s is no longer read (removed in Eneo 2.2). %s Remove the variable. See %s",
                variable.name,
                variable.note,
                UPGRADE_GUIDE_URL,
            )
        elif _is_set(variable.replacement, environ, values):
            logging.warning(
                "%s is ignored because %s is set. Remove %s.",
                variable.name,
                variable.replacement,
                variable.name,
            )
        else:
            blocking.append(
                f"{variable.name} is no longer read (removed in Eneo 2.2). "
                f"Rename it to {variable.replacement}."
            )

    if blocking:
        logging.error(
            "Eneo cannot start while removed environment variables are set:\n  %s\nSee %s",
            "\n  ".join(blocking),
            UPGRADE_GUIDE_URL,
        )
        sys.exit(1)
