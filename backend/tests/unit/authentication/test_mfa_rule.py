"""The organisation's MFA rule: which claim says MFA, and with which values."""

import json

import pytest

from eneo.authentication.mfa_rule import MfaRule
from eneo.authentication.oidc.verification import VerifiedAuthentication


def _signed_in(
    *, acr: str | None = None, amr: tuple[str, ...] | None = None
) -> VerifiedAuthentication:
    return VerifiedAuthentication(
        issuer="https://idp.example",
        client_id="eneo-client",
        subject="subject-0001",
        claims={},
        acr=acr,
        amr=amr,
        auth_time=None,
        email_claim="email",
        subject_claim="sub",
        email_verified_claims=("email_verified",),
    )


@pytest.mark.parametrize(
    ("acr", "met"),
    [
        pytest.param("level-2", True, id="one-of-the-values"),
        pytest.param("level-3", True, id="another-of-the-values"),
        pytest.param("level-1", False, id="another-value"),
        pytest.param("LEVEL-2", False, id="another-case"),
        pytest.param(None, False, id="missing"),
    ],
)
def test_an_acr_rule_is_met_by_one_of_its_values(acr, met):
    rule = MfaRule(claim="acr", values=("level-2", "level-3"))

    assert rule.met_by(_signed_in(acr=acr, amr=("pwd", "otp", "mfa"))) is met


@pytest.mark.parametrize(
    ("amr", "met"),
    [
        pytest.param(("mfa", "hwk"), True, id="every-value"),
        pytest.param(("pwd", "hwk", "mfa", "otp"), True, id="more-methods"),
        pytest.param(("mfa",), False, id="one-value-missing"),
        pytest.param((), False, id="no-methods"),
        pytest.param(None, False, id="missing"),
    ],
)
def test_an_amr_rule_is_met_by_every_one_of_its_values(amr, met):
    rule = MfaRule(claim="amr", values=("mfa", "hwk"))

    assert rule.met_by(_signed_in(acr="level-2", amr=amr)) is met


@pytest.mark.parametrize(
    "values",
    [
        pytest.param((), id="no-values"),
        pytest.param(("level-2", ""), id="an-empty-value"),
        pytest.param(("level-2", "level-2"), id="a-value-twice"),
        pytest.param(("level 2",), id="a-space-inside"),
        pytest.param((" level-2",), id="a-space-around"),
    ],
)
def test_a_rule_that_any_or_no_sign_in_would_meet_is_not_a_rule(values):
    with pytest.raises(ValueError):
        MfaRule(claim="amr", values=values)


def test_the_rule_is_read_from_the_sign_in_settings_as_it_was_written():
    rule = MfaRule(claim="amr", values=("mfa",))

    assert MfaRule.from_config({"mfa": rule.as_config()}) == rule


def test_sign_in_settings_without_a_rule_state_none():
    assert MfaRule.from_config({"client_id": "eneo-client"}) is None


@pytest.mark.parametrize(
    "stored",
    [
        pytest.param("acr", id="not-an-object"),
        pytest.param({"claim": "auth_time", "values": ["1"]}, id="another-claim"),
        pytest.param({"claim": "acr"}, id="no-values"),
        pytest.param({"claim": "acr", "values": "level-2"}, id="values-not-a-list"),
        pytest.param({"claim": "acr", "values": [2]}, id="a-value-not-text"),
        pytest.param({"claim": "amr", "values": []}, id="an-empty-list"),
    ],
)
def test_a_stored_rule_that_cannot_be_read_gives_nobody_mfa(stored):
    assert MfaRule.from_config({"mfa": stored}) is None


def test_two_rules_that_accept_the_same_are_the_same_to_a_session():
    rule = MfaRule(claim="acr", values=("level-2", "level-3"))

    assert rule.accepts() == (
        MfaRule(claim="acr", values=("level-3", "level-2"), request="claims").accepts()
    )
    assert rule.accepts() != MfaRule(claim="acr", values=("level-2",)).accepts()
    assert rule.accepts() != (
        MfaRule(claim="amr", values=("level-2", "level-3")).accepts()
    )


def test_a_rule_that_does_not_ask_adds_nothing_to_the_request():
    assert MfaRule(claim="amr", values=("mfa",)).authorization_parameters() == {}


def test_acr_values_asks_for_the_rules_values_most_wanted_first():
    rule = MfaRule(claim="acr", values=("level-3", "level-2"), request="acr_values")

    assert rule.authorization_parameters() == {"acr_values": "level-3 level-2"}


def test_claims_asks_for_acr_as_an_essential_claim_of_the_id_token():
    rule = MfaRule(claim="acr", values=("level-3", "level-2"), request="claims")

    [(name, value)] = rule.authorization_parameters().items()
    assert name == "claims"
    assert json.loads(value) == {
        "id_token": {"acr": {"essential": True, "values": ["level-3", "level-2"]}}
    }


def test_only_an_acr_rule_has_values_to_ask_for():
    with pytest.raises(ValueError):
        MfaRule(claim="amr", values=("mfa",), request="acr_values")


def test_how_eneo_asks_is_read_back_with_the_rule():
    rule = MfaRule(claim="acr", values=("level-2",), request="claims")

    assert MfaRule.from_config({"mfa": rule.as_config()}) == rule
    assert (
        MfaRule.from_config({"mfa": rule.as_config() | {"request": "prompt"}}) is None
    )
