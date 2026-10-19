"""The deployment's signing keys: made on first use, rotated by an operator,
and published through a grace period."""

from datetime import datetime, timedelta, timezone

from eneo.mcp_servers.application.mcp_oauth_signing_keys import (
    SIGNING_KEY_GRACE,
    current_signer,
    published_keys,
    rotate_signing_key,
)
from tests.unit.mcp_servers.application.test_mcp_oauth_token_provider import (
    FakeOAuthRepo,
)


async def test_the_first_use_makes_the_key_and_later_uses_share_it():
    repo = FakeOAuthRepo()

    first = await current_signer(repo)
    second = await current_signer(repo)

    assert first.kid == second.kid
    assert [key.kid for key in await published_keys(repo)] == [first.kid]


async def test_rotation_signs_with_the_new_key_and_publishes_the_old_for_a_while():
    repo = FakeOAuthRepo()
    old = await current_signer(repo)
    moment = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)

    new = await rotate_signing_key(repo, now=moment)

    assert (await current_signer(repo)).kid == new.kid != old.kid
    published = {key.kid for key in await published_keys(repo, now=moment)}
    assert published == {old.kid, new.kid}
    later = moment + SIGNING_KEY_GRACE + timedelta(seconds=1)
    assert [key.kid for key in await published_keys(repo, now=later)] == [new.kid]
