from __future__ import annotations

from dataclasses import dataclass, field
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
    draft_step_configs,
    inventory_persisted_flow_secrets,
    published_version_configs,
)

TENANT_ID = uuid4()
FLOW_ID = uuid4()


@dataclass
class _FakeEncryption:
    """Reversible prefix scheme; only registered ciphertexts decrypt."""

    prefix: str = "ENC:"
    active: bool = True
    undecryptable: set[str] = field(default_factory=set)

    def is_active(self) -> bool:
        return self.active

    def is_encrypted(self, value: str) -> bool:
        return value.startswith(self.prefix)

    def encrypt(self, plaintext: str) -> str:
        return f"{self.prefix}{plaintext}"

    def decrypt(self, ciphertext: str) -> str:
        if ciphertext in self.undecryptable:
            raise ValueError("Decryption failed: invalid token or wrong key")
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
    assert inventory.unprotected_count == 1
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


def test_inventory_accepts_secret_the_active_key_decrypts() -> None:
    inventory = inventory_persisted_flow_secrets(
        [_draft(_persisted_config(auth=HttpAuthBearer(token="ENC:token")))],
        _FakeEncryption(),
    )

    assert inventory.is_clean
    assert inventory.authored_http_configs == 1


def test_inventory_reports_prefixed_value_the_key_cannot_decrypt() -> None:
    """A row written before encryption can hold a typed prefix-shaped literal."""
    token = "ENC:not-really-ciphertext"
    inventory = inventory_persisted_flow_secrets(
        [_draft(_persisted_config(auth=HttpAuthBearer(token=token)))],
        _FakeEncryption(undecryptable={token}),
    )

    assert inventory.unprotected[0].secret_fields == ("auth.token",)


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


def test_inventory_treats_stored_secret_as_unprotected_when_key_is_inactive() -> None:
    inventory = inventory_persisted_flow_secrets(
        [_draft(_persisted_config(auth=HttpAuthBearer(token="ENC:token")))],
        _FakeEncryption(active=False),
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
    assert inventory.unreadable_count == 1
    assert inventory.unreadable[0].step_order == 1


def test_inventory_caps_samples_but_not_counts() -> None:
    configs = [
        _draft(_persisted_config(auth=HttpAuthBearer(token="plain-token")))
        for _ in range(5)
    ]

    inventory = inventory_persisted_flow_secrets(
        configs,
        _FakeEncryption(),
        sample_limit=2,
    )

    assert inventory.unprotected_count == 5
    assert len(inventory.unprotected) == 2
    assert inventory.samples_truncated
    assert not inventory.is_clean


# --- published_version_configs ---


def _version_configs(definition_json: dict[str, object]) -> list[PersistedFlowConfig]:
    return list(
        published_version_configs(
            tenant_id=TENANT_ID,
            flow_id=FLOW_ID,
            version=2,
            definition_json=definition_json,
        )
    )


def test_published_version_yields_each_step_config() -> None:
    items = _version_configs(
        {
            "steps": [
                {
                    "step_order": 1,
                    "input_config": _persisted_config(
                        auth=HttpAuthBearer(token="plain-token")
                    ),
                }
            ]
        }
    )

    inventory = inventory_persisted_flow_secrets(items, _FakeEncryption())

    assert inventory.unprotected[0].location.flow_version == 2
    assert inventory.unprotected[0].location.step_order == 1


def test_published_version_without_a_step_list_is_unreadable() -> None:
    """A version whose envelope cannot be read must not be reported clean."""
    inventory = inventory_persisted_flow_secrets(
        _version_configs({"steps": "not-a-list"}),
        _FakeEncryption(),
    )

    assert not inventory.is_clean
    assert inventory.unreadable_count == 1
    assert inventory.unreadable[0].flow_version == 2
    assert inventory.unreadable[0].config_field is None


def test_published_version_with_a_non_object_step_is_unreadable() -> None:
    inventory = inventory_persisted_flow_secrets(
        _version_configs({"steps": ["not-an-object"]}),
        _FakeEncryption(),
    )

    assert inventory.unreadable_count == 1


def test_published_step_config_that_is_not_an_object_is_unreadable() -> None:
    inventory = inventory_persisted_flow_secrets(
        _version_configs(
            {"steps": [{"step_order": 1, "input_config": "not-an-object"}]}
        ),
        _FakeEncryption(),
    )

    assert not inventory.is_clean
    assert inventory.unreadable_count == 1
    assert inventory.unreadable[0].config_field == "input_config"


def test_definition_that_is_not_an_object_is_an_unreadable_version() -> None:
    """A corrupted JSONB row must produce a finding, not crash the scan."""
    for definition in (["not", "an", "object"], "scalar", None):
        inventory = inventory_persisted_flow_secrets(
            list(
                published_version_configs(
                    tenant_id=TENANT_ID,
                    flow_id=FLOW_ID,
                    version=2,
                    definition_json=definition,
                )
            ),
            _FakeEncryption(),
        )

        assert inventory.unreadable_count == 1
        assert inventory.unreadable[0].flow_version == 2


# --- draft_step_configs ---


def test_draft_config_that_is_not_an_object_is_unreadable() -> None:
    inventory = inventory_persisted_flow_secrets(
        draft_step_configs(
            tenant_id=TENANT_ID,
            flow_id=FLOW_ID,
            step_order=4,
            input_config="not-an-object",
            output_config=None,
        ),
        _FakeEncryption(),
    )

    assert not inventory.is_clean
    assert inventory.unreadable_count == 1
    assert inventory.unreadable[0].config_field == "input_config"
    assert inventory.unreadable[0].step_order == 4


def test_absent_draft_configs_stay_clean() -> None:
    inventory = inventory_persisted_flow_secrets(
        draft_step_configs(
            tenant_id=TENANT_ID,
            flow_id=FLOW_ID,
            step_order=1,
            input_config=None,
            output_config=None,
        ),
        _FakeEncryption(),
    )

    assert inventory.is_clean
    assert inventory.scanned_configs == 2
