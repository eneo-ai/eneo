"""Environment variables that Eneo no longer reads.

Settings accepts unknown variables without complaint, so a deployment that
still sets one of these would otherwise lose the value without any sign.

Each entry has one of three outcomes:

- renamed (`replacement`): startup stops until the new name is set;
- retired setting (`old_default`): one rule for all of them. A value different
  from the old default stops startup, because it was a deliberate choice that
  would now be lost; the old default only warns, because dropping it changes
  nothing (the deployment templates shipped these defaults);
- removed with no value to lose: an error is logged and startup goes on.
"""

import logging
import sys
from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import TypeAdapter, ValidationError

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
    # Retired settings only: the value the setting defaulted to, and the
    # settings that now govern what it controlled, if there are any.
    old_default: str | None = None
    replaced_by: tuple[str, ...] = ()
    removed_in: str | None = "Eneo 2.2"
    guide_url: str | None = UPGRADE_GUIDE_URL

    @property
    def no_longer_read(self) -> str:
        return f"{self.name} is no longer read{self.removed}."

    @property
    def removed(self) -> str:
        """The release that removed it, or nothing when none is named."""
        return f" (removed in {self.removed_in})" if self.removed_in else ""


_MODULES_PERMISSION_NOTE = (
    "Module administration uses the `modules` permission instead."
)

_SPEAKER_SERVICE_NOTE = (
    "Speaker identification services are connected in Admin > Models > "
    "Transcription > Speaker identification and granted to spaces."
)

REMOVED_VARIABLES: tuple[RemovedVariable, ...] = (
    # Flows is unreleased; a value to lose is re-entered as a connection, so
    # these never block startup.
    *(
        RemovedVariable(
            name,
            note=_SPEAKER_SERVICE_NOTE,
            removed_in="Eneo 2.3",
            guide_url=None,
        )
        for name in (
            "FLOW_TRANSCRIPTION_SERVICE_URL",
            "FLOW_TRANSCRIPTION_SERVICE_API_KEY",
            "FLOW_TRANSCRIPTION_SERVICE_MODE",
            "FLOW_TRANSCRIPTION_SERVICE_SUBMIT_TIMEOUT_SECONDS",
            "FLOW_TRANSCRIPTION_SERVICE_POLL_INTERVAL_SECONDS",
            "FLOW_TRANSCRIPTION_SERVICE_RESULT_TIMEOUT_SECONDS",
        )
    ),
    # Stored admin policy deliberately takes precedence even during a rollout
    # that retains this old setting, so this entry must not block startup.
    RemovedVariable(
        "OBJECT_CONTENT_INLINE_MAXIMUM_BYTES",
        note="Upload limits are managed in Admin > File storage. The stored policy takes precedence.",
        removed_in="Eneo 2.3",
        guide_url=None,
    ),
    RemovedVariable("INTRIC_SUPER_API_KEY", replacement="ENEO_SUPER_API_KEY"),
    RemovedVariable("INTRIC_SUPER_DUPER_API_KEY", note=_MODULES_PERMISSION_NOTE),
    RemovedVariable("ENEO_SUPER_DUPER_API_KEY", note=_MODULES_PERMISSION_NOTE),
    # Crawler settings retired by the Python crawler, which keeps crawl
    # admission, leases and recovery in PostgreSQL.
    RemovedVariable(
        "TENANT_WORKER_CONCURRENCY_LIMIT",
        old_default="4",
        replaced_by=("CRAWL_JOB_TENANT_CONCURRENCY_LIMIT",),
    ),
    RemovedVariable(
        "TENANT_WORKER_SEMAPHORE_TTL_SECONDS",
        old_default="39600",
        note="The per-tenant Redis slot counter it expired is gone.",
    ),
    RemovedVariable(
        "USING_CRAWL",
        old_default="true",
        note="Crawling cannot be switched off by environment.",
    ),
    RemovedVariable(
        "CRAWL_FEEDER_ENABLED",
        old_default="true",
        note="The crawl feeder is gone; PostgreSQL dispatches scheduled crawls.",
    ),
    RemovedVariable(
        "CRAWL_FEEDER_INTERVAL_SECONDS",
        old_default="10",
        note="The feeder that paced crawl dispatch is gone; there is no pacing interval.",
    ),
    RemovedVariable(
        "CRAWL_FEEDER_BATCH_SIZE",
        old_default="10",
        note="The feeder that paced crawl dispatch is gone; there is no batch size.",
    ),
    RemovedVariable(
        "ORPHAN_CRAWL_RUN_TIMEOUT_HOURS",
        old_default="12",
        note="Stuck crawls are recovered when their PostgreSQL lease expires.",
    ),
    RemovedVariable(
        "CRAWL_STALE_THRESHOLD_MINUTES",
        old_default="30",
        note="A new crawl no longer preempts an older one of the same website.",
    ),
    RemovedVariable(
        "CRAWL_JOB_MAX_AGE_SECONDS",
        old_default="1800",
        note="Queued crawls wait in PostgreSQL admission instead of expiring.",
    ),
    RemovedVariable(
        "CRAWL_PAGE_MAX_RETRIES",
        old_default="3",
        note="The crawler retries pages by its own policy.",
    ),
    RemovedVariable(
        "CRAWL_PAGE_RETRY_DELAY",
        old_default="1.0",
        note="The crawler retries pages by its own policy.",
    ),
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


def _value_of(
    name: str, environ: Mapping[str, str], values: Mapping[str, object]
) -> str | None:
    # Settings matches names case-insensitively, and a value from an env file
    # reaches the validator as a lower-case key instead of through os.environ.
    lowered = name.lower()
    for key, value in environ.items():
        if key.lower() == lowered and value.strip():
            return value.strip()
    value = values.get(lowered)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _is_set(
    name: str, environ: Mapping[str, str], values: Mapping[str, object]
) -> bool:
    return _value_of(name, environ, values) is not None


def _is_old_default(value: str, default: str) -> bool:
    try:
        if default in ("true", "false"):
            return TypeAdapter(bool).validate_python(value) is (default == "true")
        return float(value) == float(default)
    except (ValueError, ValidationError):
        # The old validation would have rejected it; do not guess its meaning.
        return False


def _see(guide_url: str | None) -> str:
    return f" See {guide_url}" if guide_url else ""


def _check_retired_setting(
    variable: RemovedVariable,
    value: str,
    blocking: list[tuple[str, str | None]],
) -> None:
    assert variable.old_default is not None
    if _is_old_default(value, variable.old_default):
        logging.warning(
            "%s It is at its old default (%s), so dropping it changes nothing. "
            "Remove the variable.%s",
            variable.no_longer_read,
            variable.old_default,
            _see(variable.guide_url),
        )
        return
    if variable.replaced_by:
        action = f"Set {' or '.join(variable.replaced_by)} instead and remove it."
    else:
        action = "It is no longer configurable; remove it."
    lost = (
        f"{variable.name}={value} is no longer read{variable.removed}; its old "
        f"default was {variable.old_default}, so this value would be lost."
    )
    blocking.append(
        (
            " ".join(part for part in (lost, variable.note, action) if part),
            variable.guide_url,
        )
    )


def check_removed_variables(
    environ: Mapping[str, str], values: Mapping[str, object]
) -> None:
    """Log every removed variable that is still set.

    Exits when a renamed variable is set without its replacement, or a retired
    setting is set to a value other than its old default: the value would be
    lost, and the failure would otherwise surface far from its cause (a bare 401
    on every sysadmin call, or crawls that no longer follow the old limits).
    """
    # What stops startup, each with the guide that explains it.
    blocking: list[tuple[str, str | None]] = []
    for variable in REMOVED_VARIABLES:
        value = _value_of(variable.name, environ, values)
        if value is None:
            continue
        if variable.old_default is not None:
            _check_retired_setting(variable, value, blocking)
        elif variable.replacement is None:
            logging.error(
                "%s %s Remove the variable.%s",
                variable.no_longer_read,
                variable.note,
                _see(variable.guide_url),
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
                (
                    f"{variable.no_longer_read} Rename it to {variable.replacement}.",
                    variable.guide_url,
                )
            )

    if blocking:
        guides = [guide for guide in dict.fromkeys(g for _, g in blocking) if guide]
        logging.error(
            "Eneo cannot start while removed environment variables are set:\n  %s%s",
            "\n  ".join(message for message, _ in blocking),
            "\nSee " + "\n  ".join(guides) if guides else "",
        )
        sys.exit(1)
