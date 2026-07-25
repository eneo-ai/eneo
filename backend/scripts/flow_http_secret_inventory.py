#!/usr/bin/env python3
"""Report persisted Flow HTTP credentials that are not protected in storage.

Read-only. Nothing is written, re-encrypted, or deleted: the output names the
rows an administrator has to act on, and the disposition stays a human
decision.
"""

import asyncio
import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir / "src"))

from eneo.database.database import sessionmanager  # noqa: E402
from eneo.flows.infrastructure.flow_secret_inventory import (  # noqa: E402
    FlowSecretConfigLocation,
    FlowSecretInventory,
    inventory_unprotected_flow_secrets,
)
from eneo.main.config import get_settings  # noqa: E402
from eneo.settings.encryption_service import EncryptionService  # noqa: E402


def _describe(location: FlowSecretConfigLocation) -> str:
    parts = [
        location.source.value,
        f"tenant={location.tenant_id}",
        f"flow={location.flow_id}",
        "draft"
        if location.flow_version is None
        else f"version {location.flow_version}",
    ]
    if location.step_order is not None:
        parts.append(f"step {location.step_order}")
    if location.config_field is not None:
        parts.append(location.config_field)
    return " ".join(parts)


def _print_report(inventory: FlowSecretInventory, *, encryption_active: bool) -> None:
    if not encryption_active:
        print(
            "No active encryption key. Nothing can be proved protected, so every "
            "stored credential below is reported. Configure ENCRYPTION_KEY and "
            "run again before acting on this list.\n"
        )
    print(
        f"Scanned {inventory.scanned_configs} persisted step configurations, "
        f"{inventory.authored_http_configs} of them authored HTTP."
    )
    if inventory.is_clean:
        print("Every stored HTTP credential is protected.")
        return

    for finding in inventory.unprotected:
        print(
            f"UNPROTECTED {_describe(finding.location)}: "
            + ", ".join(finding.secret_fields)
        )
    for location in inventory.unreadable:
        print(f"UNREADABLE {_describe(location)}")
    print(
        f"\n{inventory.unprotected_count} unprotected, "
        f"{inventory.unreadable_count} unreadable."
    )
    if inventory.samples_truncated:
        print("Listing is capped; the counts above cover the whole deployment.")
    print(
        "\nRe-enter the credentials on the reported draft steps and publish a new "
        "version. Published versions are immutable: an affected version has to be "
        "retired rather than edited."
    )


async def main() -> int:
    settings = get_settings()
    sessionmanager.init(settings.database_url)
    encryption_service = EncryptionService(settings.encryption_key)
    try:
        async with sessionmanager.session() as session:
            inventory = await inventory_unprotected_flow_secrets(
                session,
                encryption_service,
            )
    finally:
        await sessionmanager.close()

    _print_report(inventory, encryption_active=encryption_service.is_active())
    return 0 if inventory.is_clean else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
