"""Writing the header list: id convention, secrets, and the audit diff (S5, S9)."""

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest

from eneo.model_providers.domain.model_provider import (
    MASKED_HEADER_VALUE,
    ModelProvider,
)
from eneo.model_providers.domain.outbound_header_writes import (
    OutboundHeaderWrite,
    StoredSecretUnreadable,
    apply_header_writes,
    header_audit_changes,
    retained_secret_headers,
)
from eneo.model_providers.domain.outbound_headers import OutboundHeaderConfigError


def _encrypt(value: str) -> str:
    return f"enc({value})"


def _decrypt(value: str) -> str:
    assert value.startswith("enc(") and value.endswith(")"), value
    return value[4:-1]


def _unreadable(value: str) -> str:
    """A key that changed since the secret was stored."""
    raise StoredSecretUnreadable


def _apply(
    stored: list[dict[str, Any]],
    *writes: OutboundHeaderWrite,
    decrypt: Callable[[str], str] = _decrypt,
) -> list[dict[str, Any]]:
    return apply_header_writes(
        stored,
        list(writes),
        provider_type="hosted_vllm",
        encrypt=_encrypt,
        decrypt=decrypt,
    )


def _audit(
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
    decrypt: Callable[[str], str] = _decrypt,
) -> dict[str, Any] | None:
    return header_audit_changes(before, after, decrypt=decrypt)


def _write(
    name: str = "X-Key", header_id: str | None = None, **kwargs: Any
) -> OutboundHeaderWrite:
    if "value" in kwargs:
        kwargs["value_supplied"] = True
    if "fallback" in kwargs:
        kwargs["fallback_supplied"] = True
    return OutboundHeaderWrite(id=header_id, name=name, **kwargs)


SECRET = {
    "id": "h1",
    "name": "X-Key",
    "value": "enc(sk-bf-aGVsbG8=)",
    "encoding": "none",
    "secret": True,
    "on_missing": "omit",
    "fallback": None,
    "classification": None,
}
SECRET_WITH_FALLBACK = {**SECRET, "fallback": "enc(sk-fallback)"}
PLAIN = {
    "id": "h2",
    "name": "X-Org-Unit",
    "value": "{{user.department}}",
    "encoding": "percent",
    "secret": False,
    "on_missing": "fallback",
    "fallback": "unknown",
    "classification": "organisational",
}


class TestIdConvention:
    def test_new_header_gets_an_id_and_needs_a_value(self):
        [stored] = _apply([], _write(value="eu-north"))
        assert stored["id"] and stored["value"] == "eu-north"
        with pytest.raises(OutboundHeaderConfigError, match="needs a value"):
            _apply([], _write())

    def test_id_without_value_keeps_the_stored_secret(self):
        [stored] = _apply(
            [SECRET], _write(header_id="h1", encoding="none", secret=True)
        )
        assert stored["value"] == SECRET["value"]  # same ciphertext, not re-encrypted

    def test_retained_secret_survives_repeated_round_trips(self):
        stored = [SECRET]
        for _ in range(3):
            stored = _apply(
                stored, _write(header_id="h1", encoding="none", secret=True)
            )
        assert _decrypt(stored[0]["value"]) == "sk-bf-aGVsbG8="

    def test_rename_keeps_the_secret(self):
        [stored] = _apply(
            [SECRET],
            _write(name="X-Renamed", header_id="h1", encoding="none", secret=True),
        )
        assert (stored["name"], stored["value"]) == ("X-Renamed", SECRET["value"])

    def test_id_with_value_replaces(self):
        [stored] = _apply(
            [SECRET],
            _write(header_id="h1", encoding="none", secret=True, value="sk-new"),
        )
        assert stored["value"] == "enc(sk-new)"

    def test_omitted_id_is_deleted(self):
        kept = _write(header_id="h2", name="X-Org-Unit", on_missing="fallback")
        assert _apply([SECRET, PLAIN], kept) == [PLAIN]

    def test_unknown_id_is_rejected(self):
        with pytest.raises(OutboundHeaderConfigError, match="Unknown header id"):
            _apply([PLAIN], _write(header_id="nope", value="x"))

    def test_duplicate_id_is_rejected(self):
        with pytest.raises(OutboundHeaderConfigError, match="appears twice"):
            _apply(
                [PLAIN],
                _write(header_id="h2", name="X-A"),
                _write(header_id="h2", name="X-B"),
            )

    @pytest.mark.parametrize("field", ["value", "fallback"])
    def test_the_mask_string_is_rejected(self, field: str):
        with pytest.raises(OutboundHeaderConfigError, match="omit it to keep"):
            _apply(
                [SECRET],
                _write(
                    header_id="h1",
                    encoding="none",
                    secret=True,
                    on_missing="fallback",
                    **{field: MASKED_HEADER_VALUE},
                ),
            )

    def test_validation_runs_on_the_merged_result(self):
        with pytest.raises(OutboundHeaderConfigError, match="reserved"):
            _apply([PLAIN], _write(header_id="h2", name="Authorization"))


class TestSecretFlag:
    def test_secret_value_and_fallback_are_encrypted(self):
        [stored] = _apply(
            [],
            _write(
                value="{{user.costCenter}}",
                secret=True,
                on_missing="fallback",
                fallback="sk-fallback",
            ),
        )
        assert stored["value"] == "enc({{user.costCenter}})"
        assert stored["fallback"] == "enc(sk-fallback)"

    def test_false_to_true_encrypts_the_retained_value_in_place(self):
        [stored] = _apply(
            [PLAIN],
            _write(
                header_id="h2", name="X-Org-Unit", secret=True, on_missing="fallback"
            ),
        )
        assert stored["value"] == "enc({{user.department}})"
        assert stored["fallback"] == "enc(unknown)"

    def test_true_to_false_without_the_value_is_rejected(self):
        with pytest.raises(OutboundHeaderConfigError, match="re-enter the value"):
            _apply([SECRET], _write(header_id="h1", encoding="none", secret=False))

    def test_true_to_false_without_the_fallback_is_rejected(self):
        stored = {**SECRET, "fallback": "enc(fb)", "on_missing": "fallback"}
        with pytest.raises(OutboundHeaderConfigError, match="re-enter the fallback"):
            _apply(
                [stored],
                _write(
                    header_id="h1", encoding="none", on_missing="fallback", value="v"
                ),
            )

    def test_true_to_false_with_the_value_stores_it_in_clear(self):
        [stored] = _apply(
            [SECRET], _write(header_id="h1", encoding="none", value="now-public")
        )
        assert (stored["secret"], stored["value"]) == (False, "now-public")

    def test_null_fallback_clears_it(self):
        [stored] = _apply(
            [PLAIN], _write(header_id="h2", name="X-Org-Unit", fallback=None)
        )
        assert stored["fallback"] is None


class TestUnreadableSecret:
    """A kept secret that no longer decrypts is a config error naming the
    header, so the edit that repairs it is a 400, not a 500."""

    @pytest.mark.parametrize(
        ("stored", "write", "part"),
        [
            (SECRET, _write(header_id="h1", encoding="none", secret=True), "value"),
            (
                SECRET_WITH_FALLBACK,
                _write(header_id="h1", encoding="none", secret=True, value="sk-new"),
                "fallback",
            ),
        ],
    )
    def test_keeping_it_is_refused(
        self, stored: dict[str, Any], write: OutboundHeaderWrite, part: str
    ):
        with pytest.raises(
            OutboundHeaderConfigError,
            match=f"'X-Key': the stored secret {part} cannot be read",
        ):
            _apply([stored], write, decrypt=_unreadable)

    def test_re_entering_it_never_decrypts(self):
        [stored] = _apply(
            [SECRET_WITH_FALLBACK],
            _write(
                header_id="h1",
                encoding="none",
                secret=True,
                value="sk-new",
                fallback="fb-new",
            ),
            decrypt=_unreadable,
        )
        assert (stored["value"], stored["fallback"]) == ("enc(sk-new)", "enc(fb-new)")

    def test_removing_it_never_decrypts(self):
        kept = _write(header_id="h2", name="X-Org-Unit", on_missing="fallback")
        assert _apply([SECRET, PLAIN], kept, decrypt=_unreadable) == [PLAIN]


class TestRetainedSecrets:
    """What a write keeps of a secret without the client knowing it; those
    values must not follow the provider to a new destination."""

    def test_omitted_list_keeps_every_secret(self):
        assert retained_secret_headers([SECRET, PLAIN], None) == ["X-Key"]

    @pytest.mark.parametrize(
        "write",
        [
            _write(header_id="h1", encoding="none", secret=True),
            _write(header_id="h1", encoding="none", secret=True, value="sk-new"),
        ],
    )
    def test_a_stored_fallback_is_kept_unless_supplied(
        self, write: OutboundHeaderWrite
    ):
        assert retained_secret_headers([SECRET_WITH_FALLBACK], [write]) == ["X-Key"]

    @pytest.mark.parametrize(
        ("stored", "write"),
        [
            (SECRET, _write(header_id="h1", secret=True, value="sk-new")),
            (
                SECRET_WITH_FALLBACK,
                _write(header_id="h1", secret=True, value="sk-new", fallback="fb"),
            ),
            (
                SECRET_WITH_FALLBACK,
                _write(header_id="h1", secret=True, value="sk-new", fallback=None),
            ),
            (SECRET, _write(name="X-Key", secret=True, value="sk-new")),
        ],
    )
    def test_re_entered_or_new_secrets_are_not_retained(
        self, stored: dict[str, Any], write: OutboundHeaderWrite
    ):
        assert retained_secret_headers([stored], [write]) == []

    def test_removed_and_non_secret_headers_are_not_retained(self):
        keep_plain = _write(header_id="h2", name="X-Org-Unit", fallback="unknown")
        assert retained_secret_headers([SECRET, PLAIN], [keep_plain]) == []


class TestClassification:
    """Stored with the header: a secret header's template never reaches the
    editor, which still has to show the matching privacy notice."""

    def test_the_most_sensitive_token_wins(self):
        [stored] = _apply(
            [], _write(value="{{user.department}}-{{user.employeeNumber}}", secret=True)
        )
        assert stored["classification"] == "identifying"

    def test_fixed_text_has_none(self):
        [stored] = _apply([], _write(value="eu-north"))
        assert stored["classification"] is None

    def test_a_kept_secret_keeps_its_classification(self):
        stored_secret = {
            **SECRET,
            "value": "enc({{user.externalId}})",
            "classification": "identifying",
        }
        [stored] = _apply(
            [stored_secret], _write(header_id="h1", encoding="none", secret=True)
        )
        assert stored["value"] == stored_secret["value"]
        assert stored["classification"] == "identifying"

    def test_the_public_view_shows_it_for_a_masked_secret(self):
        now = datetime.now(timezone.utc)
        provider = ModelProvider(
            id=uuid4(),
            tenant_id=uuid4(),
            name="Gateway",
            provider_type="hosted_vllm",
            credentials={},
            config={},
            is_active=True,
            created_at=now,
            updated_at=now,
            outbound_headers=[{**SECRET, "classification": "identifying"}],
        )
        [public] = provider.to_dict()["outbound_headers"]
        assert public["value"] == MASKED_HEADER_VALUE
        assert public["classification"] == "identifying"


class TestAuditChanges:
    def test_no_change(self):
        assert _audit([PLAIN], [dict(PLAIN)]) is None

    def test_non_secret_change_is_in_clear(self):
        after = {**PLAIN, "value": "{{user.division}}", "encoding": "none"}
        changes = _audit([PLAIN], [after])
        assert changes is not None
        [update] = changes["updated"]
        assert update["old"]["value"] == "{{user.department}}"
        assert update["new"]["value"] == "{{user.division}}"
        assert update["new"]["encoding"] == "none"

    def test_secret_values_are_masked_on_add_and_remove(self):
        added = _audit([], [SECRET])
        removed = _audit([SECRET], [])
        assert added is not None and added["added"][0]["value"] == MASKED_HEADER_VALUE
        assert (
            removed is not None
            and removed["removed"][0]["value"] == MASKED_HEADER_VALUE
        )

    def test_secret_flag_flip_masks_both_sides_and_records_the_transition(self):
        after = {**SECRET, "secret": False, "value": "now-public"}
        changes = _audit([SECRET], [after])
        assert changes is not None
        [update] = changes["updated"]
        assert update["old"]["value"] == update["new"]["value"] == MASKED_HEADER_VALUE
        assert (update["old"]["secret"], update["new"]["secret"]) == (True, False)
        assert update["value_changed"] is True

    def test_masked_fallback(self):
        before = {**SECRET, "fallback": "enc(fb)"}
        after = {**before, "fallback": "enc(fb2)"}
        changes = _audit([before], [after])
        assert changes is not None
        [update] = changes["updated"]
        assert update["new"]["fallback"] == MASKED_HEADER_VALUE
        assert update["fallback_changed"] is True

    def test_ticking_secret_alone_changes_no_value(self):
        [after] = _apply(
            [PLAIN],
            _write(
                header_id="h2", name="X-Org-Unit", secret=True, on_missing="fallback"
            ),
        )
        changes = _audit([PLAIN], [after])
        assert changes is not None
        [update] = changes["updated"]
        assert (update["old"]["secret"], update["new"]["secret"]) == (False, True)
        assert (update["value_changed"], update["fallback_changed"]) == (False, False)

    def test_an_unreadable_old_secret_counts_as_changed(self):
        after = {**SECRET, "value": "enc(sk-new)"}

        def decrypt(value: str) -> str:
            if value == SECRET["value"]:
                raise StoredSecretUnreadable
            return _decrypt(value)

        changes = _audit([SECRET], [after], decrypt=decrypt)
        assert changes is not None
        assert changes["updated"][0]["value_changed"] is True
