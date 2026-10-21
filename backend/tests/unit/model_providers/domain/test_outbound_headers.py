"""Outbound headers: save-time validation, per-request resolution, wire format."""

from types import SimpleNamespace
from typing import Any

import pytest

from eneo.model_providers.domain.outbound_headers import (
    MAX_HEADERS,
    MAX_RESOLVED_VALUE_BYTES,
    REGISTRY,
    OutboundHeader,
    OutboundHeaderConfigError,
    OutboundHeadersBlocked,
    evaluate_headers,
    request_headers,
    supports_outbound_headers,
    validate_headers,
)
from eneo.scim.constants import SCIM_ENTERPRISE_USER_URN


def _user(external_id: str | None = "ext-1", **enterprise: str) -> Any:
    return SimpleNamespace(
        id="user-1",
        external_id=external_id,
        scim_extensions={SCIM_ENTERPRISE_USER_URN: enterprise} if enterprise else None,
    )


def _header(value: str, name: str = "X-Org-Unit", **kwargs: Any) -> OutboundHeader:
    return OutboundHeader(id="h1", name=name, value=value, **kwargs)


def _only(headers: list[OutboundHeader], user: Any) -> Any:
    [outcome] = evaluate_headers(headers, user)
    return outcome


class TestRegistry:
    def test_is_the_closed_six_token_set(self):
        assert set(REGISTRY) == {
            "user.employeeNumber",
            "user.externalId",
            "user.costCenter",
            "user.department",
            "user.division",
            "user.organization",
        }

    def test_identifying_tokens_are_marked(self):
        identifying = {
            t for t, v in REGISTRY.items() if v.classification == "identifying"
        }
        assert identifying == {"user.employeeNumber", "user.externalId"}

    def test_email_and_username_are_not_resolvable(self):
        assert not {"user.email", "user.username", "user.name"} & set(REGISTRY)


class TestSupportedProviderTypes:
    @pytest.mark.parametrize("provider_type", ["hosted_vllm", "vllm", "HOSTED_VLLM"])
    def test_self_hosted_route_is_supported(self, provider_type: str):
        assert supports_outbound_headers(provider_type)

    @pytest.mark.parametrize(
        "provider_type", ["openai", "azure", "anthropic", "gemini"]
    )
    def test_other_routes_are_not(self, provider_type: str):
        assert not supports_outbound_headers(provider_type)


class TestValidateHeaders:
    def test_accepts_all_four_value_forms(self):
        validate_headers(
            [
                _header("eu-north", name="X-A"),
                _header("{{user.department}}", name="X-B"),
                _header("{{user.division}}/{{user.department}}", name="X-C"),
                _header("tier-{{ user.organization }}", name="X-D"),
            ],
            "hosted_vllm",
        )

    def test_refuses_unsupported_provider_type(self):
        with pytest.raises(OutboundHeaderConfigError, match="does not support"):
            validate_headers([_header("x")], "openai")

    def test_no_headers_is_valid_for_any_provider(self):
        validate_headers([], "openai")

    @pytest.mark.parametrize(
        "name",
        [
            "Authorization",
            "authorization",
            "Host",
            "Content-Type",
            "api-key",
            "User-Agent",
            "traceparent",
            "TraceState",
            "baggage",
            "x-eneo-tenant-id",
        ],
    )
    def test_reserved_names_are_rejected_case_insensitively(self, name: str):
        with pytest.raises(OutboundHeaderConfigError, match="reserved"):
            validate_headers([_header("x", name=name)], "hosted_vllm")

    @pytest.mark.parametrize(
        "name", ["X Org", "X-Org:", "X-Örg", "", "X-Org\r\n", "X-Test\n"]
    )
    def test_names_must_be_rfc9110_tokens(self, name: str):
        with pytest.raises(OutboundHeaderConfigError, match="valid HTTP header name"):
            validate_headers([_header("x", name=name)], "hosted_vllm")

    def test_name_length_bound(self):
        validate_headers([_header("x", name="X" * 64)], "hosted_vllm")
        with pytest.raises(OutboundHeaderConfigError, match="64 bytes"):
            validate_headers([_header("x", name="X" * 65)], "hosted_vllm")

    def test_case_differing_duplicate_is_rejected_naming_both(self):
        with pytest.raises(OutboundHeaderConfigError) as exc_info:
            validate_headers(
                [_header("a", name="X-Org"), _header("b", name="x-org")], "hosted_vllm"
            )
        assert "X-Org" in str(exc_info.value) and "x-org" in str(exc_info.value)

    def test_header_count_bound(self):
        headers = [_header("x", name=f"X-{i}") for i in range(MAX_HEADERS + 1)]
        with pytest.raises(OutboundHeaderConfigError, match="At most"):
            validate_headers(headers, "hosted_vllm")

    def test_unknown_token_is_named(self):
        with pytest.raises(OutboundHeaderConfigError, match="user.email"):
            validate_headers([_header("{{user.email}}")], "hosted_vllm")

    @pytest.mark.parametrize(
        "value", ["{{user.department", "user.department}}", "{{ }}"]
    )
    def test_malformed_token_syntax_is_rejected(self, value: str):
        with pytest.raises(OutboundHeaderConfigError, match="malformed"):
            validate_headers([_header(value)], "hosted_vllm")

    def test_empty_value_is_rejected(self):
        with pytest.raises(OutboundHeaderConfigError, match="needs a value"):
            validate_headers([_header("")], "hosted_vllm")

    def test_control_character_in_literal_is_rejected(self):
        with pytest.raises(OutboundHeaderConfigError, match="control character"):
            validate_headers([_header("a\r\nX-Injected: 1")], "hosted_vllm")

    def test_non_ascii_literal_under_encoding_none_is_rejected(self):
        with pytest.raises(OutboundHeaderConfigError, match="printable ASCII"):
            validate_headers([_header("Miljö", encoding="none")], "hosted_vllm")

    def test_fallback_policy_needs_a_fallback(self):
        with pytest.raises(OutboundHeaderConfigError, match="no fallback"):
            validate_headers(
                [_header("{{user.department}}", on_missing="fallback")], "hosted_vllm"
            )

    def test_fallback_cannot_contain_dynamic_values(self):
        with pytest.raises(
            OutboundHeaderConfigError, match="fallback cannot contain dynamic values"
        ):
            validate_headers(
                [
                    _header(
                        "{{user.department}}",
                        on_missing="fallback",
                        fallback="{{user.division}}",
                    )
                ],
                "hosted_vllm",
            )


class TestResolution:
    def test_token_resolves(self):
        outcome = _only([_header("{{user.department}}")], _user(department="HR"))
        assert (outcome.state, outcome.wire_value) == ("resolved", "HR")

    def test_mixed_literal_and_token(self):
        outcome = _only(
            [_header("tier-{{user.organization}}")], _user(organization="gold")
        )
        assert outcome.wire_value == "tier-gold"

    def test_external_id_token(self):
        outcome = _only([_header("{{user.externalId}}")], _user(external_id="abc"))
        assert outcome.wire_value == "abc"

    def test_provisioned_value_containing_a_token_is_sent_literally(self):
        # Second-order injection: substitution is single-pass.
        outcome = _only(
            [_header("{{user.department}}")],
            _user(department="{{user.costCenter}}", costCenter="SECRET"),
        )
        assert outcome.wire_value == "%7B%7Buser.costCenter%7D%7D"
        outcome = _only(
            [_header("{{user.department}}", encoding="none")],
            _user(department="{{user.costCenter}}", costCenter="SECRET"),
        )
        assert outcome.wire_value == "{{user.costCenter}}"

    def test_missing_with_omit(self):
        outcome = _only([_header("{{user.department}}")], _user())
        assert (outcome.state, outcome.policy, outcome.wire_value) == (
            "missing",
            "omit",
            None,
        )
        assert outcome.missing_tokens == ("user.department",)
        assert not outcome.blocks

    def test_missing_with_fallback_sends_the_literal(self):
        outcome = _only(
            [_header("{{user.department}}", on_missing="fallback", fallback="unknown")],
            _user(),
        )
        assert (outcome.state, outcome.policy, outcome.wire_value) == (
            "missing",
            "fallback",
            "unknown",
        )

    def test_missing_with_fail_blocks(self):
        outcome = _only([_header("{{user.department}}", on_missing="fail")], _user())
        assert outcome.blocks

    def test_one_missing_token_applies_the_policy_to_the_whole_header(self):
        outcome = _only(
            [_header("{{user.division}}/{{user.department}}")], _user(division="North")
        )
        assert outcome.state == "missing"
        assert outcome.wire_value is None

    def test_empty_attribute_counts_as_missing(self):
        outcome = _only([_header("{{user.department}}")], _user(department=""))
        assert outcome.state == "missing"

    def test_no_user_means_every_token_is_missing(self):
        outcome = _only([_header("{{user.department}}")], None)
        assert outcome.state == "missing"

    def test_service_key_user_without_attributes(self):
        outcome = _only([_header("{{user.department}}")], _user(external_id=None))
        assert outcome.state == "missing"

    def test_static_value_needs_no_user(self):
        outcome = _only([_header("eu-north")], None)
        assert outcome.wire_value == "eu-north"


class TestWireFormat:
    @pytest.mark.parametrize(
        ("resolved", "percent", "none"),
        [
            ("eu-north", "eu-north", "eu-north"),
            ("Sales & Marketing", "Sales %26 Marketing", "Sales & Marketing"),
            ("Miljö och hälsa", "Milj%C3%B6 och h%C3%A4lsa", None),
            ("IT/Infra", "IT%2FInfra", "IT/Infra"),
            ("100%", "100%25", "100%"),
            ("sk-bf-aGVsbG8=", "sk-bf-aGVsbG8%3D", "sk-bf-aGVsbG8="),
        ],
    )
    def test_prd_table(self, resolved: str, percent: str, none: str | None):
        user = _user(department=resolved)
        assert _only([_header("{{user.department}}")], user).wire_value == percent
        outcome = _only([_header("{{user.department}}", encoding="none")], user)
        if none is None:
            assert (outcome.state, outcome.reason) == ("invalid", "non_ascii")
        else:
            assert outcome.wire_value == none

    @pytest.mark.parametrize(
        "bad", ["a\r\nX-Injected: 1", "a\nb", "a\x00b", "a\x85b", "a\tb"]
    )
    @pytest.mark.parametrize("encoding", ["percent", "none"])
    def test_control_characters_block_and_are_never_repaired(
        self, bad: str, encoding: str
    ):
        outcome = _only(
            [_header("{{user.department}}", encoding=encoding)], _user(department=bad)
        )
        assert (outcome.state, outcome.reason, outcome.wire_value) == (
            "invalid",
            "control_character",
            None,
        )
        assert outcome.blocks

    def test_invalid_blocks_regardless_of_on_missing(self):
        outcome = _only(
            [_header("{{user.department}}", on_missing="fallback", fallback="unknown")],
            _user(department="a\r\nb"),
        )
        assert outcome.state == "invalid"

    def test_per_header_bound_applies_after_encoding(self):
        # 400 characters, 1200 bytes once percent-encoded.
        user = _user(department="ö" * 200)
        outcome = _only([_header("{{user.department}}")], user)
        assert (outcome.state, outcome.reason) == ("invalid", "value_too_long")
        within = _user(department="a" * MAX_RESOLVED_VALUE_BYTES)
        assert _only([_header("{{user.department}}")], within).state == "resolved"


class TestRequestHeaders:
    def test_builds_the_mapping_and_skips_omitted(self):
        outcomes = evaluate_headers(
            [
                _header("{{user.department}}", name="X-Dept"),
                _header("{{user.division}}", name="X-Div"),
            ],
            _user(department="HR"),
        )
        assert request_headers(outcomes) == {"X-Dept": "HR"}

    def test_every_header_omitted_gives_an_empty_mapping(self):
        outcomes = evaluate_headers([_header("{{user.department}}")], _user())
        assert request_headers(outcomes) == {}

    def test_invalid_blocks_the_request(self):
        outcomes = evaluate_headers(
            [_header("ok", name="X-A"), _header("{{user.department}}", name="X-B")],
            _user(department="a\nb"),
        )
        with pytest.raises(OutboundHeadersBlocked) as exc_info:
            request_headers(outcomes)
        assert (exc_info.value.header_name, exc_info.value.reason) == (
            "X-B",
            "control_character",
        )

    def test_fail_policy_blocks_the_request(self):
        outcomes = evaluate_headers(
            [_header("{{user.department}}", on_missing="fail")], _user()
        )
        with pytest.raises(OutboundHeadersBlocked, match="missing_required_value"):
            request_headers(outcomes)

    def test_total_bound(self):
        headers = [_header("v" * 1000, name=f"X-{i}") for i in range(5)]
        with pytest.raises(OutboundHeadersBlocked, match="total_size_exceeded"):
            request_headers(evaluate_headers(headers, None))

    def test_blocked_exception_never_carries_the_value(self):
        outcomes = evaluate_headers(
            [_header("{{user.department}}")], _user(department="LEAK\r\n")
        )
        with pytest.raises(OutboundHeadersBlocked) as exc_info:
            request_headers(outcomes)
        assert "LEAK" not in repr(exc_info.value) and "LEAK" not in str(exc_info.value)

    def test_repr_never_carries_the_value(self):
        header = _header("sk-secret", secret=True, fallback="fb-secret")
        outcome = _only([header], None)
        assert "sk-secret" not in repr(header) and "fb-secret" not in repr(header)
        assert "sk-secret" not in repr(outcome)
