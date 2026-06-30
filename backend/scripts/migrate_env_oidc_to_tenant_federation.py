#!/usr/bin/env python3

import asyncio
import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir / "src"))

from eneo.database.database import sessionmanager
from eneo.main.config import get_settings
from eneo.tenants.federation_startup_migration import (
    run_env_oidc_to_tenant_federation_migration,
)


async def main() -> int:
    settings = get_settings()
    sessionmanager.init(settings.database_url)

    try:
        migrated = await run_env_oidc_to_tenant_federation_migration()
    finally:
        await sessionmanager.close()

    print(
        "Federation migration applied." if migrated else "Federation migration skipped."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
