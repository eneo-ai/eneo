from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from eneo.flows.http_transport.authored_config import (
    SECRET_SENTINEL,
    CustomHeader,
    HttpAuthBearer,
    HttpAuthNone,
    HttpAuthoredConfig,
    HttpBody,
    HttpBodyMode,
)
from eneo.flows.infrastructure.flow_secret_inventory import (
    FlowSecretConfigLocation,
    FlowSecretConfigSource,
    PersistedFlowConfig,
    inventory_persisted_flow_secrets,
)

TENANT_ID = uuid4()
FLOW_ID = uuid4()


@dataclass
class _FakeEncryption:
    prefix: str = "ENC:"

    def is_active(self) -> bool:
        return True

    def is_encrypted(self, value: str) -> bool:
        return value.startswith(self.prefix)

    def encrypt(self, plaintext: str) -> str:
        return f"{self.prefix}{plaintext}"

    def decrypt(self, ciphertext: str) -> str:
        return ciphertext[len(self.prefix) :]


def _persisted_config(auth: object = None, **overrides: object) -> dict[str, object]:
    config = HttpAuthoredConfig(
        url="https://example.org/api",
        auth=auth or HttpAuthNone(),
        body=HttpBody(mode=HttpBodyMode.AUTO),
        custom_headers=[],
        timeout_seconds=30,
    )
    payload = config.model_dump(mode="json")
    payload.update(overrides)
    return payload


def _draft(config: dict[str, object] | None) -> PersistedFlowConfig:
    return PersistedFlowConfig(
        location=FlowSecretConfigLocation(
            source=FlowSecretConfigSource.DRAFT_STEP,
            tenant_id=TENANT_ID,
            flow_id=FLOW_ID,
            config_field="input_config",
            step_order=1,
        ),
        config=config,
    )


def _published(config: dict[str, object] | None) -> PersistedFlowConfig:
    return PersistedFlowConfig(
        location=FlowSecretConfigLocation(
            source=FlowSecretConfigSource.PUBLISHED_VERSION,
            tenant_id=TENANT_ID,
            flow_id=FLOW_ID,
            config_field="output_config",
            step_order=1,
            flow_version=3,
        ),
        config=config,
    )


def test_inventory_reports_plaintext_draft_secret() -> None:
    inventory = inventory_persisted_flow_secrets(
        [_draft(_persisted_config(auth=HttpAuthBearer(token="plain-token")))],
        _FakeEncryption(),
    )

    assert not inventory.is_clean
    assert len(inventory.unprotected) == 1
    finding = inventory.unprotected[0]
    assert finding.secret_fields == ("auth.token",)
    assert finding.location.source is FlowSecretConfigSource.DRAFT_STEP


def test_inventory_reports_plaintext_in_published_definition() -> None:
    inventory = inventory_persisted_flow_secrets(
        [_published(_persisted_config(auth=HttpAuthBearer(token="plain-token")))],
        _FakeEncryption(),
    )

    finding = inventory.unprotected[0]
    assert finding.location.source is FlowSecretConfigSource.PUBLISHED_VERSION
    assert finding.location.flow_version == 3


def test_inventory_reports_sentinel_shaped_stored_value() -> None:
    """A sentinel in storage references a secret that is not there."""
    inventory = inventory_persisted_flow_secrets(
        [_draft(_persisted_config(auth=HttpAuthBearer(token=SECRET_SENTINEL)))],
        _FakeEncryption(),
    )

    assert inventory.unprotected[0].secret_fields == ("auth.token",)


def test_inventory_accepts_encrypted_secret() -> None:
    inventory = inventory_persisted_flow_secrets(
        [_draft(_persisted_config(auth=HttpAuthBearer(token="ENC:token")))],
        _FakeEncryption(),
    )

    assert inventory.is_clean
    assert inventory.authored_http_configs == 1


def test_inventory_counts_secret_custom_headers() -> None:
    config = _persisted_config(
        custom_headers=[
            CustomHeader(name="X-Secret", value="plain", secret=True).model_dump(
                mode="json"
            ),
            CustomHeader(name="X-Public", value="plain", secret=False).model_dump(
                mode="json"
            ),
        ]
    )

    inventory = inventory_persisted_flow_secrets([_draft(config)], _FakeEncryption())

    assert inventory.unprotected[0].secret_fields == ("custom_headers[0].value",)


def test_inventory_treats_every_stored_secret_as_unprotected_without_a_key() -> None:
    inventory = inventory_persisted_flow_secrets(
        [_draft(_persisted_config(auth=HttpAuthBearer(token="ENC:token")))],
        None,
    )

    assert inventory.unprotected[0].secret_fields == ("auth.token",)


def test_inventory_skips_configs_that_are_not_authored_http() -> None:
    inventory = inventory_persisted_flow_secrets(
        [_draft({"prompt": "hello"}), _draft(None)],
        _FakeEncryption(),
    )

    assert inventory.is_clean
    assert inventory.scanned_configs == 2
    assert inventory.authored_http_configs == 0


def test_inventory_reports_authored_config_that_no_longer_parses() -> None:
    """Silence about an unreadable HTTP config would read as an all-clear."""
    inventory = inventory_persisted_flow_secrets(
        [_draft({"auth": {"mode": "not-a-real-mode"}})],
        _FakeEncryption(),
    )

    assert not inventory.is_clean
    assert inventory.unreadable == (
        FlowSecretConfigLocation(
            source=FlowSecretConfigSource.DRAFT_STEP,
            tenant_id=TENANT_ID,
            flow_id=FLOW_ID,
            config_field="input_config",
            step_order=1,
        ),
    )
