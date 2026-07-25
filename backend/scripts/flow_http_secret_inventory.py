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
    where = (
        f"version {location.flow_version}"
        if location.flow_version is not None
        else "draft"
    )
    step = "step ?" if location.step_order is None else f"step {location.step_order}"
    return (
        f"{location.source.value} tenant={location.tenant_id} "
        f"flow={location.flow_id} {where} {step} {location.config_field}"
    )


def _print_report(inventory: FlowSecretInventory) -> None:
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

    _print_report(inventory)
    return 0 if inventory.is_clean else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
