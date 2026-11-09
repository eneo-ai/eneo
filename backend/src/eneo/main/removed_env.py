"""Environment variables that Eneo no longer reads.

Settings accepts unknown variables without complaint, so a deployment that
still sets one of these would otherwise lose the value without any sign.
"""

import logging
import sys
from collections.abc import Mapping
from dataclasses import dataclass

UPGRADE_GUIDE_URL = "https://docs.eneo.ai/v2.2/guides/upgrade-2-2-0"
OIDC_MIGRATION_GUIDE_URL = (
    "https://docs.eneo.ai/guides/oidc-federation"
    "#migrate-from-the-mobilityguard-settings"
)
OIDC_STORED_MODE_GUIDE_URL = (
    "https://docs.eneo.ai/guides/oidc-federation/single-tenant"
    "#move-the-settings-into-eneo"
)


@dataclass(frozen=True)
class RemovedVariable:
    name: str
    replacement: str | None = None
    note: str = ""
    removed_in: str | None = "Eneo 2.2"
    guide_url: str = UPGRADE_GUIDE_URL

    @property
    def no_longer_read(self) -> str:
        removed = f" (removed in {self.removed_in})" if self.removed_in else ""
        return f"{self.name} is no longer read{removed}."


_MODULES_PERMISSION_NOTE = (
    "Module administration uses the `modules` permission instead."
)

REMOVED_VARIABLES: tuple[RemovedVariable, ...] = (
    RemovedVariable("INTRIC_SUPER_API_KEY", replacement="ENEO_SUPER_API_KEY"),
    RemovedVariable("INTRIC_SUPER_DUPER_API_KEY", note=_MODULES_PERMISSION_NOTE),
    RemovedVariable("ENEO_SUPER_DUPER_API_KEY", note=_MODULES_PERMISSION_NOTE),
    *(
        RemovedVariable(
            f"MOBILITYGUARD_{suffix}",
            replacement=f"OIDC_{suffix}",
            removed_in=None,
            guide_url=OIDC_MIGRATION_GUIDE_URL,
        )
        for suffix in ("DISCOVERY_ENDPOINT", "CLIENT_ID", "CLIENT_SECRET", "TENANT_ID")
    ),
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
    blocking: list[RemovedVariable] = []
    for variable in REMOVED_VARIABLES:
        if not _is_set(variable.name, environ, values):
            continue
        if variable.replacement is None:
            logging.error(
                "%s %s Remove the variable. See %s",
                variable.no_longer_read,
                variable.note,
                variable.guide_url,
            )
        elif _is_set(variable.replacement, environ, values):
            logging.warning(
                "%s is ignored because %s is set. Remove %s.",
                variable.name,
                variable.replacement,
                variable.name,
            )
        else:
            blocking.append(variable)

    if blocking:
        guides = dict.fromkeys(variable.guide_url for variable in blocking)
        logging.error(
            "Eneo cannot start while removed environment variables are set:\n  %s\nSee %s",
            "\n  ".join(
                f"{variable.no_longer_read} Rename it to {variable.replacement}."
                for variable in blocking
            ),
            "\n  ".join(guides),
        )
        sys.exit(1)
