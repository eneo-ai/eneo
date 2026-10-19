"""The deployment's signing keys for ``private_key_jwt`` client authentication.

One key signs at a time: the newest that is not retired. A retired key stays
in the published set for a grace period, so an assertion signed just before
a rotation, or a key set an authorization server cached, still verifies.
The first key is made on first use; rotation is an operator's command::

    uv run python -m eneo.mcp_servers.application.mcp_oauth_signing_keys rotate
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

from eneo.mcp_servers.domain.entities.mcp_oauth_connection import MCPOAuthSigningKey
from eneo.mcp_servers.domain.repositories.mcp_oauth_repo import MCPOAuthRepository
from eneo.mcp_servers.infrastructure.oauth.client_assertion import (
    ClientAssertionSigner,
    generate_signing_key,
)

SIGNING_KEY_GRACE = timedelta(days=7)


async def current_signer(repo: MCPOAuthRepository) -> ClientAssertionSigner:
    """The signer for new assertions; makes the deployment's first key."""
    for key in await repo.list_signing_keys():
        if not key.is_retired:
            return ClientAssertionSigner(key)
    return ClientAssertionSigner(await repo.save_signing_key(generate_signing_key()))


async def published_keys(
    repo: MCPOAuthRepository, now: Optional[datetime] = None
) -> list[MCPOAuthSigningKey]:
    """The keys the JWKS document lists: active ones and the recently retired."""
    moment = now or datetime.now(timezone.utc)
    return [
        key
        for key in await repo.list_signing_keys()
        if key.retired_at is None or key.retired_at > moment - SIGNING_KEY_GRACE
    ]


async def rotate_signing_key(
    repo: MCPOAuthRepository, now: Optional[datetime] = None
) -> MCPOAuthSigningKey:
    """Retire every active key and make a new one that signs from now on."""
    moment = now or datetime.now(timezone.utc)
    for key in await repo.list_signing_keys():
        if not key.is_retired:
            key.retired_at = moment
            await repo.save_signing_key(key)
    return await repo.save_signing_key(generate_signing_key(moment))


async def _main(argv: list[str]) -> int:
    if argv[1:] != ["rotate"]:
        print(f"usage: {argv[0]} rotate", file=sys.stderr)
        return 2
    from eneo.database.database import sessionmanager
    from eneo.main.config import get_settings
    from eneo.mcp_servers.infrastructure.repo_impl.mcp_oauth_repo_impl import (
        MCPOAuthRepoImpl,
    )
    from eneo.settings.encryption_service import EncryptionService

    settings = get_settings()
    sessionmanager.init(settings.database_url)
    async with sessionmanager.session() as session, session.begin():
        repo = MCPOAuthRepoImpl(session, EncryptionService(settings))
        key = await rotate_signing_key(repo)
    print(
        f"New signing key {key.kid} is active; retired keys stay published for "
        f"{SIGNING_KEY_GRACE.days} days."
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(sys.argv)))
