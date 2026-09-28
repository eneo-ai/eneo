"""RFC 7643 §4.3 Enterprise User extension: parsing and PATCH folding."""

from typing import Any

import pytest

from eneo.scim.constants import (
    SCIM_ENTERPRISE_USER_URN as URN,
)
from eneo.scim.constants import (
    SCIM_EXTENSION_MAX_ATTRIBUTES,
    SCIM_EXTENSION_MAX_BYTES,
    SCIM_EXTENSION_MAX_VALUE_CHARS,
)
from eneo.scim.domain.enterprise_user import (
    apply_patch_operations,
    enterprise_from_column,
    enterprise_to_column,
    parse_enterprise_object,
    split_request_extensions,
)
from eneo.scim.domain.errors import ScimHttpError, ScimValidationError
from eneo.scim.schemas.user import PatchOperation


def _op(op: str, path: str | None = None, value: Any = None) -> PatchOperation:
    return PatchOperation(op=op, path=path, value=value)


class TestParseEnterpriseObject:
    def test_keeps_known_string_attributes(self):
        assert parse_enterprise_object(
            {"department": "Sales", "costCenter": "4130", "employeeNumber": "701984"}
        ) == {"department": "Sales", "costCenter": "4130", "employeeNumber": "701984"}

    def test_names_are_case_insensitive_and_stored_canonically(self):
        assert parse_enterprise_object({"COSTCENTER": "4130", "department": "HR"}) == {
            "costCenter": "4130",
            "department": "HR",
        }

    def test_same_attribute_twice_in_different_case_is_rejected(self):
        with pytest.raises(ScimValidationError, match="more than once"):
            parse_enterprise_object({"costCenter": "1", "costcenter": "2"})

    def test_unknown_attributes_are_dropped(self):
        assert parse_enterprise_object({"department": "HR", "shoeSize": "44"}) == {
            "department": "HR"
        }

    @pytest.mark.parametrize("empty", [None, ""])
    def test_null_and_empty_string_mean_absent(self, empty: str | None):
        assert parse_enterprise_object({"department": empty, "division": "X"}) == {
            "division": "X"
        }

    @pytest.mark.parametrize("bad", [{"nested": "object"}, 4130, True, ["a"]])
    def test_non_string_value_is_rejected_not_coerced(self, bad: Any):
        with pytest.raises(ScimValidationError, match="costCenter"):
            parse_enterprise_object({"costCenter": bad})

    def test_whole_object_must_be_an_object(self):
        with pytest.raises(ScimValidationError, match="must be an object"):
            parse_enterprise_object(["department"])

    def test_null_whole_object_is_empty(self):
        assert parse_enterprise_object(None) == {}

    def test_manager_keeps_value_and_ref_and_drops_read_only_display_name(self):
        assert parse_enterprise_object(
            {
                "manager": {
                    "value": "26118915-6090-4610-87e4-49d8ca9f808d",
                    "$ref": "../Users/26118915-6090-4610-87e4-49d8ca9f808d",
                    "displayName": "John Smith",
                }
            }
        ) == {
            "manager": {
                "value": "26118915-6090-4610-87e4-49d8ca9f808d",
                "$ref": "../Users/26118915-6090-4610-87e4-49d8ca9f808d",
            }
        }

    def test_manager_with_only_display_name_is_absent(self):
        assert parse_enterprise_object({"manager": {"displayName": "John"}}) == {}

    def test_manager_bare_string_is_taken_as_its_value(self):
        # Some IdPs send the manager id as a bare string in PATCH.
        assert parse_enterprise_object({"manager": "mgr-1"}) == {
            "manager": {"value": "mgr-1"}
        }

    @pytest.mark.parametrize("bad", [42, ["mgr-1"], {"value": 42}])
    def test_malformed_manager_is_rejected(self, bad: Any):
        with pytest.raises(ScimValidationError, match="manager"):
            parse_enterprise_object({"manager": bad})


class TestLimits:
    def test_value_at_the_bound_is_accepted(self):
        value = "x" * SCIM_EXTENSION_MAX_VALUE_CHARS
        assert parse_enterprise_object({"department": value}) == {"department": value}

    def test_value_past_the_bound_is_rejected(self):
        with pytest.raises(ScimValidationError, match="characters"):
            parse_enterprise_object(
                {"department": "x" * (SCIM_EXTENSION_MAX_VALUE_CHARS + 1)}
            )

    def test_attribute_count_at_the_bound_is_accepted(self):
        attributes = {f"unknown{i}": "v" for i in range(SCIM_EXTENSION_MAX_ATTRIBUTES)}
        assert parse_enterprise_object(attributes) == {}

    def test_attribute_count_past_the_bound_is_rejected(self):
        attributes = {
            f"unknown{i}": "v" for i in range(SCIM_EXTENSION_MAX_ATTRIBUTES + 1)
        }
        with pytest.raises(ScimValidationError, match="attributes"):
            parse_enterprise_object(attributes)

    def test_serialised_size_past_the_bound_is_rejected(self):
        # Each value is under the per-value bound; together they exceed the total.
        chunk = "x" * SCIM_EXTENSION_MAX_VALUE_CHARS
        count = SCIM_EXTENSION_MAX_BYTES // SCIM_EXTENSION_MAX_VALUE_CHARS + 1
        attributes = {f"unknown{i}": chunk for i in range(count)}
        with pytest.raises(ScimValidationError, match="bytes"):
            parse_enterprise_object(attributes)


class TestSplitRequestExtensions:
    def test_separates_enterprise_object_from_other_keys(self):
        present, raw, ignored = split_request_extensions(
            {
                URN: {"department": "HR"},
                "urn:example:custom:1.0:User": {"badge": "7"},
                "notAUrn": 1,
            }
        )
        assert present is True
        assert raw == {"department": "HR"}
        assert sorted(ignored) == ["notAUrn", "urn:example:custom:1.0:User"]

    def test_urn_key_is_matched_case_insensitively(self):
        present, raw, _ = split_request_extensions({URN.lower(): {"division": "D"}})
        assert present is True
        assert raw == {"division": "D"}

    def test_urn_twice_in_different_case_is_rejected(self):
        with pytest.raises(ScimValidationError, match="more than once"):
            split_request_extensions({URN: {}, URN.upper(): {}})

    def test_absent(self):
        assert split_request_extensions(None) == (False, None, [])


class TestColumnRoundTrip:
    def test_empty_extension_is_stored_as_null(self):
        assert enterprise_to_column({}) is None

    def test_round_trip(self):
        enterprise = {"department": "HR"}
        column = enterprise_to_column(enterprise)
        assert column == {URN: {"department": "HR"}}
        assert enterprise_from_column(column) == enterprise

    def test_from_null_column(self):
        assert enterprise_from_column(None) == {}


class TestPatchOperations:
    CURRENT = {"department": "Sales", "costCenter": "4130"}

    def test_replace_fully_qualified_attribute(self):
        result = apply_patch_operations(
            self.CURRENT, [_op("replace", f"{URN}:department", "HR")]
        )
        assert result == {"department": "HR", "costCenter": "4130"}

    def test_add_absent_attribute(self):
        result = apply_patch_operations(
            self.CURRENT, [_op("Add", f"{URN}:division", "North")]
        )
        assert result == {**self.CURRENT, "division": "North"}

    def test_path_less_urn_object_merges(self):
        result = apply_patch_operations(
            self.CURRENT, [_op("Replace", None, {URN: {"department": "HR"}})]
        )
        assert result == {"department": "HR", "costCenter": "4130"}

    def test_path_less_fully_qualified_keys(self):
        result = apply_patch_operations(
            self.CURRENT,
            [_op("replace", None, {f"{URN}:department": "HR", "active": True})],
        )
        assert result == {"department": "HR", "costCenter": "4130"}

    def test_path_less_null_attribute_removes_it(self):
        result = apply_patch_operations(
            self.CURRENT, [_op("replace", None, {URN: {"department": None}})]
        )
        assert result == {"costCenter": "4130"}

    def test_replace_whole_urn_merges_named_attributes(self):
        # RFC 7644 §3.5.2.3: attributes not mentioned in the value are unchanged.
        result = apply_patch_operations(
            self.CURRENT, [_op("replace", URN, {"department": "HR"})]
        )
        assert result == {"department": "HR", "costCenter": "4130"}

    def test_remove_attribute(self):
        result = apply_patch_operations(
            self.CURRENT, [_op("Remove", f"{URN}:department")]
        )
        assert result == {"costCenter": "4130"}

    def test_remove_whole_extension(self):
        assert apply_patch_operations(self.CURRENT, [_op("remove", URN)]) == {}

    def test_null_value_removes_attribute(self):
        result = apply_patch_operations(
            self.CURRENT, [_op("replace", f"{URN}:department", None)]
        )
        assert result == {"costCenter": "4130"}

    def test_attribute_name_in_path_is_case_insensitive(self):
        result = apply_patch_operations(
            self.CURRENT, [_op("replace", f"{URN.lower()}:DEPARTMENT", "HR")]
        )
        assert result["department"] == "HR"

    def test_manager_bare_string(self):
        result = apply_patch_operations({}, [_op("Add", f"{URN}:manager", "mgr-1")])
        assert result == {"manager": {"value": "mgr-1"}}

    def test_manager_sub_attribute_set_and_remove(self):
        result = apply_patch_operations(
            {"manager": {"value": "mgr-1"}},
            [_op("replace", f"{URN}:manager.$ref", "../Users/mgr-1")],
        )
        assert result == {"manager": {"value": "mgr-1", "$ref": "../Users/mgr-1"}}
        result = apply_patch_operations(
            result,
            [
                _op("remove", f"{URN}:manager.value"),
                _op("remove", f"{URN}:manager.$ref"),
            ],
        )
        assert result == {}

    def test_unknown_attribute_path_is_invalid_path(self):
        with pytest.raises(ScimHttpError) as exc_info:
            apply_patch_operations(
                self.CURRENT, [_op("replace", f"{URN}:shoeSize", "44")]
            )
        assert exc_info.value.status_code == 400
        assert exc_info.value.scim_type == "invalidPath"

    def test_display_name_sub_attribute_path_is_invalid_path(self):
        with pytest.raises(ScimHttpError, match="manager.displayName"):
            apply_patch_operations(
                {}, [_op("replace", f"{URN}:manager.displayName", "John")]
            )

    def test_invalid_operation_rejects_the_whole_request(self):
        with pytest.raises(ScimValidationError):
            apply_patch_operations(
                self.CURRENT,
                [
                    _op("replace", f"{URN}:department", "HR"),
                    _op("replace", f"{URN}:costCenter", {"nested": "object"}),
                ],
            )

    def test_input_is_not_mutated(self):
        current = dict(self.CURRENT)
        apply_patch_operations(current, [_op("remove", URN)])
        assert current == self.CURRENT

    def test_core_and_other_urn_paths_are_ignored(self):
        operations = [
            _op("replace", "active", False),
            _op("replace", 'emails[type eq "work"].value', "a@example.com"),
            _op("replace", "urn:example:custom:1.0:User:badge", "7"),
            _op("replace", f"{URN}X:department", "not ours"),
        ]
        assert apply_patch_operations(self.CURRENT, operations) == self.CURRENT
