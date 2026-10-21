import time
from types import SimpleNamespace
from uuid import uuid4

import altcha
import pytest
import redis.exceptions

from eneo.widgets.application.altcha_service import AltchaService
from eneo.widgets.domain.exceptions import (
    ChallengeInvalidError,
    WidgetProtectionUnavailableError,
)
from eneo.widgets.domain.widget import Widget

WIDGET = Widget.create(
    tenant_id=uuid4(), space_id=uuid4(), target_id=uuid4(), name="w"
).model_copy(update={"id": uuid4()})


class FakeRedis:
    def __init__(self, *, fail: bool = False) -> None:
        self.store: dict[str, bytes] = {}
        self.fail = fail

    async def set(self, key, value, nx=False, ex=None):
        if self.fail:
            raise redis.exceptions.ConnectionError("down")
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True


def _settings(**overrides) -> SimpleNamespace:
    base = dict(
        url_signing_key="signing-key",
        widget_altcha_cost=2_000,
        widget_altcha_key_prefix="00",
        widget_altcha_challenge_ttl_seconds=300,
        widget_rate_limit_fail_open=False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _solve(challenge: dict) -> str:
    parsed = altcha.Challenge.from_dict(challenge)
    solution = altcha.solve_challenge(parsed)
    assert solution is not None
    return altcha.Payload(challenge=parsed, solution=solution).to_base64()


async def test_challenge_can_be_solved_and_verified_once():
    service = AltchaService(FakeRedis(), settings=_settings())
    challenge = service.create_challenge(WIDGET)
    assert challenge["parameters"]["algorithm"] == "SHA-256"
    assert challenge["parameters"]["cost"] == 2_000
    assert challenge["parameters"]["expiresAt"] > int(time.time())

    payload = _solve(challenge)
    await service.verify(payload, WIDGET)
    with pytest.raises(ChallengeInvalidError) as exc:
        await service.verify(payload, WIDGET)
    assert exc.value.code == "challenge_replayed"


async def test_challenge_from_another_deployment_is_rejected():
    issuer = AltchaService(FakeRedis(), settings=_settings(url_signing_key="other"))
    verifier = AltchaService(FakeRedis(), settings=_settings())
    payload = _solve(issuer.create_challenge(WIDGET))
    with pytest.raises(ChallengeInvalidError) as exc:
        await verifier.verify(payload, WIDGET)
    assert exc.value.code == "challenge_invalid"


async def test_challenge_from_another_widget_is_rejected():
    service = AltchaService(FakeRedis(), settings=_settings())
    other = WIDGET.model_copy(update={"id": uuid4()})
    payload = _solve(service.create_challenge(other))
    with pytest.raises(ChallengeInvalidError) as exc:
        await service.verify(payload, WIDGET)
    assert exc.value.code == "challenge_invalid"
    await service.verify(payload, other)


async def test_expired_challenge_is_rejected():
    service = AltchaService(
        FakeRedis(), settings=_settings(widget_altcha_challenge_ttl_seconds=1)
    )
    challenge = service.create_challenge(WIDGET)
    challenge["parameters"]["expiresAt"] = int(time.time()) - 5
    # Re-sign is impossible without the secret, so the expired stamp fails
    # either as expired or as a signature mismatch — both refuse.
    with pytest.raises(ChallengeInvalidError):
        await service.verify(_solve(challenge), WIDGET)


async def test_malformed_payload_is_rejected():
    service = AltchaService(FakeRedis(), settings=_settings())
    with pytest.raises(ChallengeInvalidError):
        await service.verify("not-base64-json", WIDGET)


async def test_redis_loss_fails_closed_by_default_and_open_when_configured():
    payload = _solve(
        AltchaService(FakeRedis(), settings=_settings()).create_challenge(WIDGET)
    )
    with pytest.raises(WidgetProtectionUnavailableError):
        await AltchaService(FakeRedis(fail=True), settings=_settings()).verify(
            payload, WIDGET
        )
    await AltchaService(
        FakeRedis(fail=True), settings=_settings(widget_rate_limit_fail_open=True)
    ).verify(payload, WIDGET)
