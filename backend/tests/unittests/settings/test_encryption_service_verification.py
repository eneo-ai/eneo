"""Behavior of side-effect-free ciphertext verification.

`can_decrypt` exists so a caller checking many stored credentials at once can
tell protected from unprotected without emitting a diagnostic record per
invalid value. `decrypt` keeps its error log, because callers that mask a
credential swallow the failure and that log is their only visibility.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from eneo.settings import encryption_service as encryption_service_module
from eneo.settings.encryption_service import EncryptionService


@pytest.fixture
def service() -> EncryptionService:
    return EncryptionService(Fernet.generate_key().decode())


def _capture_service_logger(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, str]]:
    """Record what the module logs, whatever the deployment log handler does."""
    records: list[tuple[str, str]] = []

    class _Recorder:
        def __getattr__(self, level: str):
            def log(message: str, *args: object, **kwargs: object) -> None:
                records.append((level, str(message)))

            return log

    monkeypatch.setattr(encryption_service_module, "logger", _Recorder())
    return records


def test_can_decrypt_accepts_own_ciphertext(service: EncryptionService) -> None:
    assert service.can_decrypt(service.encrypt("api-key"))


def test_can_decrypt_rejects_plaintext(service: EncryptionService) -> None:
    assert not service.can_decrypt("api-key")


def test_can_decrypt_rejects_a_typed_literal_wearing_the_prefix(
    service: EncryptionService,
) -> None:
    assert not service.can_decrypt(f"{EncryptionService.VERSION_PREFIX}not-a-token")


def test_can_decrypt_rejects_ciphertext_from_another_key(
    service: EncryptionService,
) -> None:
    other = EncryptionService(Fernet.generate_key().decode())

    assert not service.can_decrypt(other.encrypt("api-key"))


def _authentic_token_holding_non_utf8(service: EncryptionService) -> str:
    """Ciphertext this key authenticates, whose plaintext is not a string."""
    fernet: Fernet = getattr(service, "_fernet")
    token = fernet.encrypt(b"\xff").decode()
    return EncryptionService.VERSION_PREFIX + token


def test_can_decrypt_rejects_authentic_ciphertext_that_is_not_text(
    service: EncryptionService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Authentic but undecodable is still a failure to recover the credential."""
    records = _capture_service_logger(monkeypatch)

    assert not service.can_decrypt(_authentic_token_holding_non_utf8(service))
    assert records == []


def test_decrypt_turns_undecodable_plaintext_into_its_documented_error(
    service: EncryptionService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = _capture_service_logger(monkeypatch)

    with pytest.raises(ValueError):
        service.decrypt(_authentic_token_holding_non_utf8(service))

    assert [level for level, _ in records] == ["error"]


def test_can_decrypt_rejects_everything_without_a_key() -> None:
    keyless = EncryptionService(None)

    assert not keyless.can_decrypt(f"{EncryptionService.VERSION_PREFIX}anything")


def test_can_decrypt_is_silent_for_many_invalid_values(
    service: EncryptionService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifying an estate must not produce one record per invalid value."""
    records = _capture_service_logger(monkeypatch)

    for index in range(60):
        assert not service.can_decrypt(
            f"{EncryptionService.VERSION_PREFIX}invalid-{index}"
        )

    assert records == []


def test_decrypt_still_logs_its_failure(
    service: EncryptionService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Callers that swallow the error rely on this log for visibility."""
    records = _capture_service_logger(monkeypatch)

    with pytest.raises(ValueError):
        service.decrypt(f"{EncryptionService.VERSION_PREFIX}not-a-token")

    assert [level for level, _ in records] == ["error"]


def test_decrypt_round_trips(service: EncryptionService) -> None:
    assert service.decrypt(service.encrypt("api-key")) == "api-key"
