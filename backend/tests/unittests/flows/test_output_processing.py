"""Tests for eneo.flows.output_processing — pure function module."""

from __future__ import annotations

import copy
import dataclasses
import json
import tracemalloc
from typing import Any

import pytest
from referencing import Registry

from eneo.completion_models.infrastructure.tenant_model_capabilities import (
    _COMMON_SCHEMA_KEYWORDS,
)
from eneo.flows.domain import strict_schema_limits
from eneo.flows.domain.strict_schema_limits import (
    COMMON_STRICT_SCHEMA_LIMITS,
    STRICT_SCHEMA_LIMITS_BY_PROVIDER,
    StrictSchemaLimits,
    strict_schema_limits_for,
)
from eneo.flows.flow_run_error import FlowRunContractViolation
from eneo.flows.output_processing import (
    _STRICT_RESPONSE_KEYWORDS,
    _contract_named_pointer,
    compile_validators,
    conform_keys_to_schema,
    first_strict_response_violation,
    parse_json_output,
    validate_against_contract,
    validate_schema_syntax,
)
from eneo.main.exceptions import TypedIOValidationException

# --- parse_json_output ---


def test_parse_json_output_valid_object():
    result = parse_json_output('{"key": "val"}')
    assert result == {"key": "val"}


def test_parse_json_output_valid_array():
    result = parse_json_output("[1, 2, 3]")
    assert result == [1, 2, 3]


def test_parse_json_output_accepts_fenced_json_object():
    result = parse_json_output('```json\n{"key": "val"}\n```')
    assert result == {"key": "val"}


def test_parse_json_output_accepts_wrapped_json_object():
    result = parse_json_output('Here is the result:\n{"key": "val"}\nTack!')
    assert result == {"key": "val"}


@pytest.mark.parametrize(
    "text",
    [
        '{"sections": [{"text": "first"}, {"text": "unfinished',
        'Result:\n{"sections": [{"text": "first"}, {"text": "unfinished',
        '{"first": true}\n{"second": true}',
        '{"first": true}\n{"second":',
        '```json\n{"first": true}\n```\n```json\n{"second": true}\n```',
    ],
)
def test_parse_json_output_does_not_salvage_a_partial_result(text):
    with pytest.raises(TypedIOValidationException) as exc_info:
        parse_json_output(text)
    assert exc_info.value.code == "typed_io_output_parse_failed"


def test_parse_json_output_preserves_all_items_in_large_result():
    import json

    data = {"sections": [{"text": f"Uppgift {index}"} for index in range(3000)]}
    assert parse_json_output(json.dumps(data, ensure_ascii=False)) == data


def test_parse_json_output_empty_response_has_clearer_message():
    with pytest.raises(TypedIOValidationException, match="response was empty"):
        parse_json_output("   \n\t  ")


def test_parse_json_output_invalid_json():
    with pytest.raises(TypedIOValidationException, match="not valid JSON"):
        parse_json_output("not json at all")


def test_parse_json_output_scalar_rejected():
    with pytest.raises(
        TypedIOValidationException, match="Expected JSON object or array"
    ):
        parse_json_output('"just a string"')


def test_parse_json_output_error_code():
    with pytest.raises(TypedIOValidationException) as exc_info:
        parse_json_output("not json")
    assert exc_info.value.code == "typed_io_output_parse_failed"


# --- validate_against_contract ---


def test_validate_against_contract_passes():
    schema = {
        "type": "object",
        "required": ["name"],
        "properties": {"name": {"type": "string"}},
    }
    validate_against_contract({"name": "Alice"}, schema, label="test")


def test_validate_against_contract_fails():
    schema = {
        "type": "object",
        "required": ["name"],
        "properties": {"name": {"type": "string"}},
    }
    with pytest.raises(TypedIOValidationException, match="test"):
        validate_against_contract({}, schema, label="test")


def test_validate_against_contract_error_code():
    schema = {"type": "object", "required": ["x"]}
    with pytest.raises(TypedIOValidationException) as exc_info:
        validate_against_contract({}, schema, label="output")
    assert exc_info.value.code == "typed_io_contract_violation"


def test_contract_error_locates_nested_wrong_type_without_echoing_records():
    schema = {
        "type": "object",
        "properties": {
            "areas": {
                "type": "object",
                "properties": {"family": {"type": "object"}},
            }
        },
    }
    data = {"areas": {"family": [{"text": "Private source content"}]}}

    with pytest.raises(TypedIOValidationException) as exc_info:
        validate_against_contract(data, schema, label="Step 3 output")

    assert exc_info.value.code == "typed_io_contract_violation"
    assert "/areas/family" in str(exc_info.value)
    assert "object" in str(exc_info.value)
    assert "Private source content" not in str(exc_info.value)


def test_contract_error_bounds_record_content_and_escapes_json_pointer():
    schema = {
        "type": "object",
        "properties": {"a/b~c": {"type": "string", "maxLength": 10}},
    }
    with pytest.raises(TypedIOValidationException) as exc_info:
        validate_against_contract({"a/b~c": "Private" * 10000}, schema, label="Output")

    assert "/a~1b~0c" in str(exc_info.value)
    assert "maxLength" in str(exc_info.value)
    assert len(str(exc_info.value)) < 500
    assert exc_info.value.context == {
        "json_pointer": "/a~1b~0c",
        "schema_rule": "maxLength",
    }


_NESTED_CONTRACT = {
    "type": "object",
    "required": ["summary"],
    "properties": {
        "summary": {
            "type": "object",
            "required": ["verdict"],
            "properties": {"verdict": {"type": "string"}, "note": {"type": "string"}},
        }
    },
}


@pytest.mark.parametrize("side", ["input", "output"])
def test_contract_violation_context_names_its_side_rule_and_location(side):
    with pytest.raises(TypedIOValidationException) as exc_info:
        validate_against_contract(
            {"summary": {"note": "Private note"}},
            _NESTED_CONTRACT,
            label="Step 2 output",
            side=side,
        )

    assert exc_info.value.context == {
        "json_pointer": "/summary",
        "schema_rule": "required",
        "contract_side": side,
    }
    assert str(exc_info.value) == (
        "Step 2 output at /summary: 'verdict' is a required property"
    )


def test_root_contract_violation_is_the_empty_pointer_and_keeps_its_message():
    with pytest.raises(TypedIOValidationException) as exc_info:
        validate_against_contract([], _NESTED_CONTRACT, label="Out", side="output")

    assert exc_info.value.context == {
        "json_pointer": "",
        "schema_rule": "type",
        "contract_side": "output",
    }
    assert str(exc_info.value) == "Out at /: Value is not of type 'object'."


def test_empty_property_name_is_a_pointer_distinct_from_the_root():
    schema = {"type": "object", "properties": {"": {"type": "string"}}}
    with pytest.raises(TypedIOValidationException) as exc_info:
        validate_against_contract({"": 1}, schema, label="Out")

    assert exc_info.value.context == {"json_pointer": "/", "schema_rule": "type"}
    assert str(exc_info.value) == "Out at /: Value is not of type 'string'."


def test_contract_violation_beyond_the_pointer_bound_records_no_location():
    key = "k" * 450
    schema = {"type": "object", "properties": {key: {"type": "string"}}}
    with pytest.raises(TypedIOValidationException) as exc_info:
        validate_against_contract({key: 1}, schema, label="Out", side="output")

    assert FlowRunContractViolation.from_context(exc_info.value.context) is None
    assert str(exc_info.value) == (
        f"Out at {('/' + key)[:400]}: Value is not of type 'string'."
    )


def test_pointer_at_exactly_the_bound_is_recorded_in_full():
    key = "k" * 399
    schema = {"type": "object", "properties": {key: {"type": "string"}}}
    with pytest.raises(TypedIOValidationException) as exc_info:
        validate_against_contract({key: 1}, schema, label="Out", side="output")

    violation = FlowRunContractViolation.from_context(exc_info.value.context)
    assert violation is not None
    assert violation.json_pointer == "/" + key


_DATA_KEYS = ["19121212-1212", "a@b.se", "åäö 😀", "a/b~c", "", "0"]
_FREE_FORM_CONTRACTS = {
    "additionalProperties": {
        "type": "object",
        "additionalProperties": {"type": "string"},
    },
    "patternProperties": {
        "type": "object",
        "patternProperties": {".*": {"type": "string"}},
        "additionalProperties": False,
    },
}


@pytest.mark.parametrize("key", _DATA_KEYS)
@pytest.mark.parametrize("keyword", sorted(_FREE_FORM_CONTRACTS))
def test_pointer_stops_before_a_key_that_comes_from_the_data(keyword, key):
    with pytest.raises(TypedIOValidationException) as exc_info:
        validate_against_contract(
            {key: 5}, _FREE_FORM_CONTRACTS[keyword], label="Out", side="output"
        )

    # The pointer is stored on the run; the message keeps the full location.
    assert exc_info.value.context["json_pointer"] == ""
    assert not key or key not in repr(exc_info.value.context)
    token = key.replace("~", "~0").replace("/", "~1")
    assert str(exc_info.value) == f"Out at /{token}: Value is not of type 'string'."


def test_pointer_keeps_declared_names_and_indices_up_to_the_first_data_key():
    schema = {
        "type": "object",
        "properties": {
            "people": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "tags": {
                            "type": "object",
                            "additionalProperties": {"type": "integer"},
                        }
                    },
                },
            }
        },
    }
    data = {"people": [{"tags": {}}, {"tags": {"kalle@example.se": "x"}}]}
    with pytest.raises(TypedIOValidationException) as exc_info:
        validate_against_contract(data, schema, label="Out", side="input")

    assert exc_info.value.context["json_pointer"] == "/people/1/tags"
    assert "kalle@example.se" in str(exc_info.value)


def test_pointer_follows_references_and_prefix_items_to_declared_names():
    schema = {
        "type": "array",
        "prefixItems": [
            {"$ref": "#/$defs/person"},
            {"type": "object", "properties": {"x": {"type": "string"}}},
        ],
        "$defs": {
            "person": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
            }
        },
    }
    with pytest.raises(TypedIOValidationException) as exc_info:
        validate_against_contract([{"name": 1}], schema, label="Out", side="output")
    assert exc_info.value.context["json_pointer"] == "/0/name"

    with pytest.raises(TypedIOValidationException) as exc_info:
        validate_against_contract([{}, {"x": 1}], schema, label="Out", side="output")
    assert exc_info.value.context["json_pointer"] == "/1/x"


def test_pointer_is_the_ancestor_when_a_data_key_was_cut_before_the_failure():
    schema = {
        "type": "object",
        "properties": {
            "people": {
                "type": "object",
                "additionalProperties": {
                    "type": "object",
                    "required": ["verdict"],
                },
            }
        },
    }
    with pytest.raises(TypedIOValidationException) as exc_info:
        validate_against_contract(
            {"people": {"a@b.se": {}}}, schema, label="Out", side="output"
        )

    assert exc_info.value.context["json_pointer"] == "/people"
    assert "/people/a@b.se" in str(exc_info.value)


def _reference_chain(length: int) -> dict[str, object]:
    """A publish-valid contract whose `verdict` sits behind `length` local references."""
    defs: dict[str, object] = {
        f"h{index}": {"$ref": f"#/$defs/h{index + 1}"} for index in range(length - 1)
    }
    defs[f"h{length - 1}"] = {
        "type": "object",
        "properties": {"verdict": {"type": "string"}},
    }
    return {"$ref": "#/$defs/h0", "$defs": defs}


@pytest.mark.parametrize("length", [1, 16, 17, 40, 400])
def test_pointer_keeps_its_location_through_any_finite_reference_chain(length):
    with pytest.raises(TypedIOValidationException) as exc_info:
        validate_against_contract(
            {"verdict": 1}, _reference_chain(length), label="Out", side="output"
        )

    assert exc_info.value.context["json_pointer"] == "/verdict"


def test_pointer_stops_at_the_last_declared_name_when_references_cycle():
    # The data-keyed rule fails first, so validation ends before it could follow the cycle.
    schema = {
        "type": "object",
        "properties": {
            "outer": {
                "additionalProperties": {"type": "string"},
                "$ref": "#/$defs/a",
            }
        },
        "$defs": {"a": {"$ref": "#/$defs/b"}, "b": {"$ref": "#/$defs/a"}},
    }
    with pytest.raises(TypedIOValidationException) as exc_info:
        validate_against_contract(
            {"outer": {"inner": 1}}, schema, label="Out", side="output"
        )

    assert exc_info.value.context["json_pointer"] == "/outer"


def test_pointer_walk_crawls_the_contract_once_however_many_references_it_follows(
    monkeypatch,
):
    crawls_with_work: list[int] = []
    original = Registry.crawl

    def counting_crawl(self):
        if getattr(self, "_uncrawled", None):
            crawls_with_work.append(1)
        return original(self)

    monkeypatch.setattr(Registry, "crawl", counting_crawl)

    pointer = _contract_named_pointer(_reference_chain(40), ["verdict"])

    assert pointer == "/verdict"
    assert len(crawls_with_work) == 1


def test_pointer_keeps_an_index_the_contract_reaches_through_composition():
    schema = {"type": "array", "allOf": [{"items": {"type": "string"}}]}
    with pytest.raises(TypedIOValidationException) as exc_info:
        validate_against_contract([1], schema, label="Out", side="output")

    assert exc_info.value.context["json_pointer"] == "/0"


def test_pointer_names_a_required_property_the_contract_does_not_describe():
    schema = {
        "type": "object",
        "required": ["flag"],
        "additionalProperties": {"type": "string"},
    }
    with pytest.raises(TypedIOValidationException) as exc_info:
        validate_against_contract({"flag": 1}, schema, label="Out", side="output")

    assert exc_info.value.context["json_pointer"] == "/flag"


def test_pointer_stops_where_the_contract_composes_its_shape():
    schema = {
        "type": "object",
        "properties": {
            "outer": {
                "allOf": [
                    {
                        "type": "object",
                        "properties": {"inner": {"type": "string"}},
                    }
                ]
            }
        },
    }
    with pytest.raises(TypedIOValidationException) as exc_info:
        validate_against_contract(
            {"outer": {"inner": 1}}, schema, label="Out", side="output"
        )

    assert exc_info.value.context["json_pointer"] == "/outer"


def test_false_schema_violation_names_no_rule():
    # jsonschema reports a false subschema without a keyword (validator None).
    schema = {"type": "object", "properties": {"x": False}}
    with pytest.raises(TypedIOValidationException) as exc_info:
        validate_against_contract({"x": 1}, schema, label="Out", side="output")

    assert exc_info.value.context == {"json_pointer": "", "contract_side": "output"}
    assert str(exc_info.value) == (
        "Out at /: Value does not satisfy schema rule 'None'."
    )


def test_conform_keys_to_schema_drops_extra_item_property():
    schema = {
        "type": "object",
        "required": ["beslutslista"],
        "properties": {
            "beslutslista": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["rubrik", "beslut", "omrostning"],
                    "properties": {
                        "rubrik": {"type": "string"},
                        "beslut": {"type": "string"},
                        "omrostning": {"type": "boolean"},
                        "roster_for": {"type": "string"},
                        "roster_emot": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            }
        },
        "additionalProperties": False,
    }
    data = {
        "beslutslista": [
            {
                "rubrik": "Budget",
                "beslut": "Godkänd",
                "omrostning": False,
                "rubrik_kommentar": "extra",
            }
        ]
    }

    result = conform_keys_to_schema(data, schema)

    assert result.dropped_paths == ("/beslutslista/0/rubrik_kommentar",)
    assert "rubrik_kommentar" not in data["beslutslista"][0]
    validate_against_contract(data, schema, label="Step 4 output")


def test_conform_keys_to_schema_leaves_permissive_schemas_unchanged():
    schema = {
        "type": "object",
        "properties": {"rubrik": {"type": "string"}},
    }
    data = {"rubrik": "Budget", "rubrik_kommentar": "kept"}

    result = conform_keys_to_schema(data, schema)

    assert result.dropped_paths == ()
    assert data["rubrik_kommentar"] == "kept"


def test_conform_keys_to_schema_is_deep_and_idempotent():
    schema = {
        "type": "object",
        "properties": {
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"title": {"type": "string"}},
                                "additionalProperties": False,
                            },
                        }
                    },
                    "additionalProperties": False,
                },
            }
        },
        "additionalProperties": False,
    }
    data = {
        "sections": [
            {
                "items": [
                    {"title": "One", "unexpected": "drop"},
                ],
                "section_extra": "drop",
            }
        ],
    }

    first = conform_keys_to_schema(data, schema)
    second = conform_keys_to_schema(data, schema)

    assert first.dropped_paths == (
        "/sections/0/section_extra",
        "/sections/0/items/0/unexpected",
    )
    assert second.dropped_paths == ()
    assert data == {"sections": [{"items": [{"title": "One"}]}]}


def test_conform_keys_to_schema_skips_composition_nodes():
    schema = {
        "oneOf": [
            {
                "type": "object",
                "properties": {"title": {"type": "string"}},
                "additionalProperties": False,
            }
        ]
    }
    data = {"title": "One", "unexpected": "kept"}

    result = conform_keys_to_schema(data, schema)

    assert result.dropped_paths == ()
    assert data["unexpected"] == "kept"


def test_pruned_output_still_fails_missing_required():
    schema = {
        "type": "object",
        "required": ["rubrik"],
        "properties": {"rubrik": {"type": "string"}},
        "additionalProperties": False,
    }
    data = {"rubrik_kommentar": "drop"}

    result = conform_keys_to_schema(data, schema)

    assert result.dropped_paths == ("/rubrik_kommentar",)
    with pytest.raises(TypedIOValidationException, match="'rubrik' is a required"):
        validate_against_contract(data, schema, label="Step output")


def test_pruned_output_still_fails_wrong_type():
    schema = {
        "type": "object",
        "required": ["omrostning"],
        "properties": {"omrostning": {"type": "boolean"}},
        "additionalProperties": False,
    }
    data = {"omrostning": "nej", "extra": "drop"}

    result = conform_keys_to_schema(data, schema)

    assert result.dropped_paths == ("/extra",)
    with pytest.raises(TypedIOValidationException, match="is not of type"):
        validate_against_contract(data, schema, label="Step output")


# --- key spelling: a key that differs from a contract key only by canonically
# equivalent forms, combining marks or case ---


def _bedomning_contract(*, closed: bool) -> dict:
    contract: dict = {
        "type": "object",
        "required": ["krav", "bedomning"],
        "properties": {"krav": {"type": "string"}, "bedomning": {"type": "string"}},
    }
    if closed:
        contract["additionalProperties"] = False
    return contract


@pytest.mark.parametrize("closed", [True, False])
def test_conform_keys_renames_a_respelled_key_at_the_root(closed):
    data = {"krav": "K1", "bedömning": "Avvikelse"}
    schema = _bedomning_contract(closed=closed)

    result = conform_keys_to_schema(data, schema)

    assert data == {"krav": "K1", "bedomning": "Avvikelse"}
    assert result.renamed_sample == (("/bedömning", "/bedomning"),)
    assert result.dropped_paths == ()
    validate_against_contract(data, schema, label="Step 2 output")


@pytest.mark.parametrize(
    ("declared", "written"),
    [
        ("bedomning", "bedömning"),
        ("bedomning", "Bedomning"),
        ("bedomning", "BEDÖMNING"),
        ("aland", "Åland"),
        ("overgang", "Övergång"),
        ("resume", "résumé"),
        ("forelagga", "FÖRELÄGGA"),
        # The declared key may itself carry the accent or the capital.
        ("bedömning", "Bedomning"),
        ("Bedomning", "bedömning"),
        ("Åland", "aland"),
        # Canonically equivalent forms are the same letter: Kelvin, Angstrom, Ohm.
        ("k", "\u212a"),
        ("a", "\u212b"),
        ("\u03c9", "\u2126"),
    ],
)
def test_conform_keys_renames_canonically_equivalent_spellings(declared, written):
    schema = {
        "type": "object",
        "required": [declared],
        "properties": {declared: {"type": "string"}},
    }
    data = {written: "värde"}

    result = conform_keys_to_schema(data, schema)

    assert data == {declared: "värde"}
    assert result.renamed_sample == ((f"/{written}", f"/{declared}"),)


@pytest.mark.parametrize(
    ("declared", "written"),
    [
        # Symbols, other letters and separators are not diacritics or case.
        ("andel", "Andel (%)"),
        ("k", "kø"),
        ("id", "名前_id"),
        ("total_summa", "Total-Summa"),
        ("total_summa", "total summa"),
        ("bedomning", "bedomning_"),
        # A compatibility form is not canonically equivalent: circled and fullwidth.
        ("1", "\u2460"),
        ("1", "\uff11"),
        ("a", "\uff41"),
    ],
)
def test_conform_keys_never_renames_a_key_that_is_more_than_a_respelling(
    declared, written
):
    schema = {
        "type": "object",
        "required": [declared],
        "properties": {declared: {"type": "string"}},
    }
    data = {written: "värde"}

    result = conform_keys_to_schema(data, schema)

    assert data == {written: "värde"}
    assert result.renamed_sample == ()


def test_conform_keys_keeps_the_renamed_key_at_its_position():
    data = {"krav": "K1", "bedömning": "Avvikelse", "omrade": "O"}
    schema = {
        "type": "object",
        "required": ["bedomning"],
        "properties": {
            "krav": {"type": "string"},
            "bedomning": {"type": "string"},
            "omrade": {"type": "string"},
        },
    }

    conform_keys_to_schema(data, schema)

    assert list(data) == ["krav", "bedomning", "omrade"]


def test_conform_keys_leaves_other_undeclared_keys_of_an_open_object_alone():
    data = {"krav": "K1", "bedömning": "Avvikelse", "fri_anmarkning": "kept"}

    result = conform_keys_to_schema(data, _bedomning_contract(closed=False))

    assert data == {"krav": "K1", "bedomning": "Avvikelse", "fri_anmarkning": "kept"}
    assert result.dropped_paths == ()


def test_conform_keys_renames_a_respelled_key_in_a_nested_object():
    schema = {
        "type": "object",
        "required": ["bilaga"],
        "properties": {
            "bilaga": {
                "type": "object",
                "required": ["underlag_och_osakerhet"],
                "properties": {"underlag_och_osakerhet": {"type": ["string", "null"]}},
                "additionalProperties": False,
            }
        },
        "additionalProperties": False,
    }
    data = {"bilaga": {"underlag_och_osäkerhet": "Ritning saknas"}}

    result = conform_keys_to_schema(data, schema)

    assert data == {"bilaga": {"underlag_och_osakerhet": "Ritning saknas"}}
    assert result.renamed_sample == (
        ("/bilaga/underlag_och_osäkerhet", "/bilaga/underlag_och_osakerhet"),
    )
    validate_against_contract(data, schema, label="Step 3 output")


def test_conform_keys_conforms_the_children_of_a_renamed_key_too():
    schema = {
        "type": "object",
        "required": ["bilaga"],
        "properties": {
            "bilaga": {
                "type": "object",
                "required": ["underlag_och_osakerhet"],
                "properties": {"underlag_och_osakerhet": {"type": ["string", "null"]}},
                "additionalProperties": False,
            }
        },
        "additionalProperties": False,
    }
    data = {"Bilaga": {"underlag_och_osäkerhet": "Ritning saknas", "extra": 1}}

    result = conform_keys_to_schema(data, schema)

    assert data == {"bilaga": {"underlag_och_osakerhet": "Ritning saknas"}}
    assert result.renamed_sample == (
        ("/Bilaga", "/bilaga"),
        ("/bilaga/underlag_och_osäkerhet", "/bilaga/underlag_och_osakerhet"),
    )
    assert result.dropped_paths == ("/bilaga/extra",)
    validate_against_contract(data, schema, label="Step 3 output")


def test_conform_keys_renames_every_drifted_item_of_an_array_and_only_those():
    schema = {
        "type": "object",
        "required": ["avvikelser"],
        "properties": {
            "avvikelser": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["vad_vi_avser_att_forelagga_om"],
                    "properties": {
                        "vad_vi_avser_att_forelagga_om": {"type": ["string", "null"]}
                    },
                    "additionalProperties": False,
                },
            }
        },
        "additionalProperties": False,
    }
    data = {
        "avvikelser": [
            {"vad_vi_avser_att_forelagga_om": "Rätta"},
            {"vad_vi_avser_att_forelägga_om": "Komplettera"},
            {"vad_vi_avser_att_forelägga_om": "Redovisa"},
            {"vad_vi_avser_att_forelägga_om": "Åtgärda"},
        ]
    }

    result = conform_keys_to_schema(data, schema)

    assert [item["vad_vi_avser_att_forelagga_om"] for item in data["avvikelser"]] == [
        "Rätta",
        "Komplettera",
        "Redovisa",
        "Åtgärda",
    ]
    assert result.renamed_sample == tuple(
        (
            f"/avvikelser/{index}/vad_vi_avser_att_forelägga_om",
            f"/avvikelser/{index}/vad_vi_avser_att_forelagga_om",
        )
        for index in (1, 2, 3)
    )
    assert result.dropped_paths == ()
    validate_against_contract(data, schema, label="Step 4 output")


def test_conform_keys_prunes_a_second_spelling_only_as_a_closed_object_always_did():
    data = {"krav": "K1", "bedomning": "Avvikelse", "bedömning": "Godkänd"}

    result = conform_keys_to_schema(data, _bedomning_contract(closed=True))

    assert data == {"krav": "K1", "bedomning": "Avvikelse"}
    assert result.renamed_sample == ()
    assert result.dropped_paths == ("/bedömning",)


@pytest.mark.parametrize(
    ("schema", "data"),
    [
        (
            _bedomning_contract(closed=False),
            {"krav": "K1", "bedomning": "", "bedömning": "Avvikelse"},
        ),
        (
            {"type": "object", "properties": {"andel": {"type": "number"}}},
            {"andel": 5, "Andel": 12},
        ),
        (
            {"type": "object", "additionalProperties": {"type": "integer"}},
            {"Örebro": 1, "orebro": 2},
        ),
        (
            {
                "type": "object",
                "properties": {"x_a": {"type": "integer"}},
                "patternProperties": {"^x_": {"type": "integer"}},
            },
            {"x_a": 2, "x_A": 1},
        ),
    ],
)
def test_conform_keys_keeps_both_spellings_of_an_open_object(schema, data):
    before = dict(data)

    result = conform_keys_to_schema(data, schema)

    assert data == before
    assert result.renamed_sample == ()
    assert result.dropped_paths == ()


def test_conform_keys_is_a_no_op_when_every_key_is_the_contract_key():
    for closed in (True, False):
        data = {"bedomning": "Avvikelse", "krav": "K1"}

        result = conform_keys_to_schema(data, _bedomning_contract(closed=closed))

        assert list(data.items()) == [("bedomning", "Avvikelse"), ("krav", "K1")]
        assert result.renamed_sample == ()
        assert result.dropped_paths == ()


def test_conform_keys_never_renames_a_different_word():
    schema = {
        "type": "object",
        "required": ["utgaaende_tillgangar"],
        "properties": {"utgaaende_tillgangar": {"type": "array"}},
        "additionalProperties": False,
    }
    data = {"utgaaande_tillgangar": [], "bedomningar": []}

    result = conform_keys_to_schema(data, schema)

    assert data == {}
    assert result.renamed_sample == ()
    assert result.dropped_paths == ("/utgaaande_tillgangar", "/bedomningar")
    with pytest.raises(TypedIOValidationException, match="'utgaaende_tillgangar'"):
        validate_against_contract(data, schema, label="Step 1 output")


def test_conform_keys_never_renames_a_different_word_in_an_open_object():
    schema = _bedomning_contract(closed=False)
    data = {"krav": "K1", "bedomningar": "annat ord"}

    result = conform_keys_to_schema(data, schema)

    assert data == {"krav": "K1", "bedomningar": "annat ord"}
    assert result.renamed_sample == ()


def test_conform_keys_renames_nothing_when_two_spellings_claim_the_same_key():
    data = {"krav": "K1", "bedömning": "Avvikelse", "Bedömning": "Godkänd"}

    result = conform_keys_to_schema(data, _bedomning_contract(closed=False))

    assert data == {"krav": "K1", "bedömning": "Avvikelse", "Bedömning": "Godkänd"}
    assert result.renamed_sample == ()


# A pass must never become a failure: only a required key that is missing is ever
# renamed. The contract already fails there, so a rename can only trade one failure
# for another. Every other key is left to the pruning, respelled or not.


@pytest.mark.parametrize("closed", [True, False])
@pytest.mark.parametrize(
    ("declared", "written", "value"),
    [
        ("kommentar", "Kommentar", "Bra"),
        ("kommentar", "Kommentar", None),
        ("antal", "Antal", 3),
    ],
)
def test_conform_keys_treats_a_respelled_optional_key_exactly_as_the_pruning_did(
    declared, written, value, closed
):
    schema = {
        "type": "object",
        "required": ["summary"],
        "properties": {"summary": {"type": "string"}, declared: {}},
    }
    if closed:
        schema["additionalProperties"] = False
    data = {"summary": "s", written: value}

    result = conform_keys_to_schema(data, schema)

    assert result.renamed_sample == ()
    if closed:
        assert data == {"summary": "s"}
        assert result.dropped_paths == (f"/{written}",)
    else:
        assert data == {"summary": "s", written: value}
        assert result.dropped_paths == ()
    validate_against_contract(data, schema, label="Step 1 output")


@pytest.mark.parametrize("closed", [True, False])
def test_conform_keys_leaves_a_respelled_optional_parent_and_its_children_as_they_were(
    closed,
):
    schema = {
        "type": "object",
        "properties": {
            "bilaga": {
                "type": "object",
                "required": ["bedomning"],
                "properties": {"bedomning": {"type": "string"}},
            }
        },
    }
    if closed:
        schema["additionalProperties"] = False
    data = {"Bilaga": {"bedömning": "A"}}

    result = conform_keys_to_schema(data, schema)

    assert result.renamed_sample == ()
    assert data == ({} if closed else {"Bilaga": {"bedömning": "A"}})


def test_conform_keys_declines_when_two_declared_keys_share_a_spelling():
    schema = {
        "type": "object",
        "required": ["bedomning", "Bedomning"],
        "properties": {
            "bedomning": {"type": "string"},
            "Bedomning": {"type": "string"},
        },
    }
    respelled = {"bedömning": "x"}
    exact_capital = {"Bedomning": "x"}

    assert conform_keys_to_schema(respelled, schema).renamed_sample == ()
    assert conform_keys_to_schema(exact_capital, schema).renamed_sample == ()
    assert respelled == {"bedömning": "x"}
    assert exact_capital == {"Bedomning": "x"}


def test_conform_keys_renames_a_required_key_even_when_its_value_does_not_fit():
    schema = {
        "type": "object",
        "required": ["antal"],
        "properties": {"antal": {"type": "integer"}},
        "additionalProperties": False,
    }
    data = {"Antal": "tre"}

    result = conform_keys_to_schema(data, schema)

    assert data == {"antal": "tre"}
    assert result.renamed_sample == (("/Antal", "/antal"),)
    with pytest.raises(TypedIOValidationException, match="is not of type"):
        validate_against_contract(data, schema, label="Step 1 output")


def _drifted_rows(count: int) -> tuple[dict, dict]:
    schema = {
        "type": "object",
        "required": ["rows"],
        "properties": {
            "rows": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["bedomning"],
                    "properties": {"bedomning": {"type": "string"}},
                    "additionalProperties": False,
                },
            }
        },
    }
    return schema, {"rows": [{"bedömning": "x"} for _ in range(count)]}


def test_conform_keys_counts_every_rename_but_reports_a_bounded_sample():
    schema, data = _drifted_rows(100_000)

    result = conform_keys_to_schema(data, schema)

    assert result.renamed_count == 100_000
    assert len(result.renamed_sample) == 20
    assert result.renamed_sample[0] == ("/rows/0/bedömning", "/rows/0/bedomning")
    assert result.renamed_sample[-1] == ("/rows/19/bedömning", "/rows/19/bedomning")
    assert data["rows"][-1] == {"bedomning": "x"}


def _peak_additional_bytes(count: int) -> int:
    schema, data = _drifted_rows(count)
    tracemalloc.start()
    try:
        before, _ = tracemalloc.get_traced_memory()
        conform_keys_to_schema(data, schema)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return peak - before


def test_conform_keys_memory_does_not_grow_with_the_number_of_renames():
    few = _peak_additional_bytes(400)
    many = _peak_additional_bytes(4_000)

    # Ten times the rows, the same bounded record.
    assert many < 3 * few


def test_conform_keys_skips_composition_nodes_like_the_pruner():
    schema = {"oneOf": [_bedomning_contract(closed=True)]}
    data = {"krav": "K1", "bedömning": "Avvikelse"}

    result = conform_keys_to_schema(data, schema)

    assert data == {"krav": "K1", "bedömning": "Avvikelse"}
    assert result.renamed_sample == ()


# --- validate_schema_syntax ---


def test_validate_schema_syntax_valid():
    validate_schema_syntax({"type": "object"}, label="test")


def test_validate_schema_syntax_invalid():
    with pytest.raises(TypedIOValidationException, match="not a valid JSON Schema"):
        validate_schema_syntax({"type": "not_a_type"}, label="test")


def test_validate_schema_syntax_error_code():
    with pytest.raises(TypedIOValidationException) as exc_info:
        validate_schema_syntax({"type": "not_a_type"}, label="test")
    assert exc_info.value.code == "typed_io_invalid_schema"


# --- compile_validators ---


class _FakeStep:
    def __init__(self, step_order, input_contract=None, output_contract=None):
        self.step_order = step_order
        self.input_contract = input_contract
        self.output_contract = output_contract


def test_compile_validators_reusable():
    steps = [
        _FakeStep(
            1, input_contract={"type": "object"}, output_contract={"type": "array"}
        ),
        _FakeStep(2, output_contract={"type": "string"}),
    ]
    compiled = compile_validators(steps)
    assert ("input", 1) in compiled
    assert ("output", 1) in compiled
    assert ("input", 2) not in compiled
    assert ("output", 2) in compiled
    # Verify they're actual validators
    compiled[("input", 1)].validate({})
    compiled[("output", 1)].validate([])


def test_compile_validators_empty_steps():
    assert compile_validators([]) == {}


def test_compile_validators_no_contracts():
    steps = [_FakeStep(1)]
    assert compile_validators(steps) == {}


def test_compile_validators_keeps_explicit_empty_contracts():
    steps = [_FakeStep(1, input_contract={}, output_contract={})]

    compiled = compile_validators(steps)

    assert ("input", 1) in compiled
    assert ("output", 1) in compiled
    compiled[("input", 1)].validate({"anything": True})
    compiled[("output", 1)].validate(["anything"])


# --- first_strict_response_violation ---


def _closed(**properties: Any) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _strings(count: int, prefix: str = "p") -> dict[str, Any]:
    return _closed(**{f"{prefix}{index}": {"type": "string"} for index in range(count)})


def _nested_objects(levels: int) -> dict[str, Any]:
    contract = _closed(leaf={"type": "string"})
    for _ in range(levels - 1):
        contract = _closed(child=contract)
    return contract


STRICT_ELIGIBLE: dict[str, dict[str, Any]] = {
    "primitives": _closed(
        a={"type": "string"},
        b={"type": "number"},
        c={"type": "integer"},
        d={"type": "boolean"},
    ),
    "enum_and_const": _closed(
        kind={"type": "string", "enum": ["x", "y"]},
        level={"type": "integer", "enum": [1, 2]},
        flag={"type": "boolean", "const": True},
        tag={"type": "string", "const": "fixed"},
    ),
    "enum_and_const_of_the_declared_type": _closed(
        a={"type": "number", "enum": [1, 2.5]},
        b={"type": ["integer", "null"], "const": 3},
        c={"type": "boolean", "enum": [True, False]},
    ),
    "finite_floats_are_scalars": _closed(
        a={"type": "number", "enum": [1.5, 1e300]},
        b={"type": "number", "const": -2.5},
    ),
    "nullable_union_both_orders": _closed(
        a={"type": ["string", "null"]}, b={"type": ["null", "integer"]}
    ),
    "nested_objects": _closed(outer=_closed(inner=_closed(leaf={"type": "string"}))),
    "array_of_closed_objects": _closed(
        rows={"type": "array", "items": _closed(n={"type": "number"})}
    ),
    "array_of_primitives": _closed(tags={"type": "array", "items": {"type": "string"}}),
    "annotations": _closed(a={"type": "string", "title": "A", "description": "The a"}),
    "property_names_are_data": _closed(
        type={"type": "string"},
        required={"type": "string"},
        minItems={"type": "string"},
        **{"$ref": {"type": "string"}, "~a/b": {"type": "string"}},
    ),
}


@pytest.mark.parametrize("contract", STRICT_ELIGIBLE.values(), ids=STRICT_ELIGIBLE)
def test_strict_response_eligible_shapes_have_no_violation(contract):
    before = copy.deepcopy(contract)
    assert first_strict_response_violation(contract) is None
    assert contract == before


def _with(contract: dict[str, Any], **changes: Any) -> dict[str, Any]:
    return {**contract, **changes}


def _without(contract: dict[str, Any], key: str) -> dict[str, Any]:
    return {k: v for k, v in contract.items() if k != key}


_ONE = _closed(a={"type": "string"})
_TWO = _closed(a={"type": "string"}, b={"type": "string"})


def _prop(schema: dict[str, Any]) -> dict[str, Any]:
    return _closed(a=schema)


STRICT_INELIGIBLE = {
    "array_root": (
        {"type": "array", "items": _ONE},
        "",
        "root_not_object",
    ),
    "string_root": ({"type": "string"}, "", "root_not_object"),
    "boolean_root": (True, "", "boolean_schema"),
    "non_dict_root": (["x"], "", "schema_not_object"),
    "none_root": (None, "", "schema_not_object"),
    "boolean_property": (_prop(True), "/properties/a", "boolean_schema"),
    "non_dict_property": (_prop("string"), "/properties/a", "schema_not_object"),
    "additional_absent": (
        _without(_ONE, "additionalProperties"),
        "",
        "object_open",
    ),
    "additional_true": (_with(_ONE, additionalProperties=True), "", "object_open"),
    "additional_schema": (
        _with(_ONE, additionalProperties={"type": "string"}),
        "",
        "object_open",
    ),
    "nested_object_open": (
        _prop(
            {
                "type": "object",
                "properties": {"b": {"type": "string"}},
                "required": ["b"],
            }
        ),
        "/properties/a",
        "object_open",
    ),
    "required_missing": (_without(_ONE, "required"), "", "required_mismatch"),
    "required_subset": (_with(_TWO, required=["a"]), "", "required_mismatch"),
    "required_superset": (
        _with(_ONE, required=["a", "ghost"]),
        "",
        "required_mismatch",
    ),
    "required_duplicate": (_with(_TWO, required=["a", "a"]), "", "required_mismatch"),
    "required_duplicate_beside_all_names": (
        _with(_TWO, required=["a", "b", "a"]),
        "",
        "required_mismatch",
    ),
    "required_not_a_list": (_with(_ONE, required="a"), "", "required_mismatch"),
    "empty_object": (_closed(), "", "structure_mismatch"),
    "properties_absent": (
        {"type": "object", "required": [], "additionalProperties": False},
        "",
        "structure_mismatch",
    ),
    "properties_not_a_dict": (_with(_ONE, properties=["a"]), "", "structure_mismatch"),
    "schema_keyword": (
        _with(_ONE, **{"$schema": "x"}),
        "/$schema",
        "keyword_outside_grammar",
    ),
    "id_keyword": (_with(_ONE, **{"$id": "x"}), "/$id", "keyword_outside_grammar"),
    "ref_keyword": (
        _prop({"$ref": "#/$defs/a"}),
        "/properties/a/$ref",
        "keyword_outside_grammar",
    ),
    "defs_keyword": (
        _with(_ONE, **{"$defs": {}}),
        "/$defs",
        "keyword_outside_grammar",
    ),
    "composition": (
        _prop({"anyOf": [{"type": "string"}]}),
        "/properties/a/anyOf",
        "keyword_outside_grammar",
    ),
    "pattern": (
        _prop({"type": "string", "pattern": "^a"}),
        "/properties/a/pattern",
        "keyword_outside_grammar",
    ),
    "format": (
        _prop({"type": "string", "format": "date"}),
        "/properties/a/format",
        "keyword_outside_grammar",
    ),
    "default": (
        _prop({"type": "string", "default": "x"}),
        "/properties/a/default",
        "keyword_outside_grammar",
    ),
    "unknown_keyword": (
        _prop({"type": "string", "x-note": 1}),
        "/properties/a/x-note",
        "keyword_outside_grammar",
    ),
    "type_missing": (_prop({}), "/properties/a", "type_outside_grammar"),
    "type_unknown": (_prop({"type": "null"}), "/properties/a", "type_outside_grammar"),
    "three_type_list": (
        _prop({"type": ["string", "integer", "null"]}),
        "/properties/a",
        "type_outside_grammar",
    ),
    "two_primitives_without_null": (
        _prop({"type": ["string", "integer"]}),
        "/properties/a",
        "type_outside_grammar",
    ),
    "container_plus_null": (
        _prop({"type": ["array", "null"], "items": {"type": "string"}}),
        "/properties/a",
        "type_outside_grammar",
    ),
    "object_plus_null": (
        _prop({"type": ["object", "null"]}),
        "/properties/a",
        "type_outside_grammar",
    ),
    "properties_on_non_object": (
        _prop({"type": "string", "properties": {}}),
        "/properties/a",
        "structure_mismatch",
    ),
    "items_on_non_array": (
        _prop({"type": "string", "items": {"type": "string"}}),
        "/properties/a",
        "structure_mismatch",
    ),
    "array_without_items": (
        _prop({"type": "array"}),
        "/properties/a",
        "structure_mismatch",
    ),
    "enum_on_object": (
        _with(_ONE, enum=["a"]),
        "",
        "structure_mismatch",
    ),
    "empty_enum": (
        _prop({"type": "string", "enum": []}),
        "/properties/a",
        "enum_invalid",
    ),
    "enum_with_null": (
        _prop({"type": ["string", "null"], "enum": ["a", None]}),
        "/properties/a",
        "enum_invalid",
    ),
    "enum_with_object": (
        _prop({"type": "string", "enum": [{"a": 1}]}),
        "/properties/a",
        "enum_invalid",
    ),
    "enum_not_a_list": (
        _prop({"type": "string", "enum": "ab"}),
        "/properties/a",
        "enum_invalid",
    ),
    "enum_integers_on_a_string": (
        _prop({"type": "string", "enum": [1, 2]}),
        "/properties/a",
        "enum_type_mismatch",
    ),
    "enum_string_on_an_integer": (
        _prop({"type": "integer", "enum": ["a"]}),
        "/properties/a",
        "enum_type_mismatch",
    ),
    "enum_float_on_an_integer": (
        _prop({"type": "integer", "enum": [1.5]}),
        "/properties/a",
        "enum_type_mismatch",
    ),
    "enum_bool_on_a_string": (
        _prop({"type": "string", "enum": [True]}),
        "/properties/a",
        "enum_type_mismatch",
    ),
    "enum_bool_on_a_number": (
        _prop({"type": "number", "enum": [True]}),
        "/properties/a",
        "enum_type_mismatch",
    ),
    "enum_bool_on_an_integer": (
        _prop({"type": "integer", "enum": [1, False]}),
        "/properties/a",
        "enum_type_mismatch",
    ),
    "enum_number_on_a_boolean": (
        _prop({"type": "boolean", "enum": [1]}),
        "/properties/a",
        "enum_type_mismatch",
    ),
    "enum_mismatch_on_a_nullable_union": (
        _prop({"type": ["integer", "null"], "enum": ["a"]}),
        "/properties/a",
        "enum_type_mismatch",
    ),
    "enum_duplicate": (
        _prop({"type": "string", "enum": ["x", "x"]}),
        "/properties/a",
        "enum_invalid",
    ),
    "const_integer_on_a_string": (
        _prop({"type": "string", "const": 5}),
        "/properties/a",
        "const_type_mismatch",
    ),
    "const_bool_on_an_integer": (
        _prop({"type": "integer", "const": True}),
        "/properties/a",
        "const_type_mismatch",
    ),
    "open_dict_without_properties": (
        {"type": "object", "additionalProperties": True},
        "",
        "object_open",
    ),
    "enum_infinity": (
        _prop({"type": "number", "enum": [1.0, float("inf")]}),
        "/properties/a",
        "enum_invalid",
    ),
    "enum_negative_infinity": (
        _prop({"type": "number", "enum": [float("-inf")]}),
        "/properties/a",
        "enum_invalid",
    ),
    "enum_not_a_number": (
        _prop({"type": "number", "enum": [float("nan")]}),
        "/properties/a",
        "enum_invalid",
    ),
    "const_not_a_number": (
        _prop({"type": "number", "const": float("nan")}),
        "/properties/a",
        "const_invalid",
    ),
    "const_infinity_parsed_from_json": (
        _prop(json.loads('{"type": "number", "const": 1e999}')),
        "/properties/a",
        "const_invalid",
    ),
    "enum_and_const_that_conflict": (
        _prop({"type": "string", "enum": ["a"], "const": "b"}),
        "/properties/a",
        "enum_with_const",
    ),
    "enum_and_const_that_agree": (
        _prop({"type": "string", "enum": ["a", "b"], "const": "a"}),
        "/properties/a",
        "enum_with_const",
    ),
    "const_null": (
        _prop({"type": ["string", "null"], "const": None}),
        "/properties/a",
        "const_invalid",
    ),
    "const_object": (
        _prop({"type": "string", "const": {"a": 1}}),
        "/properties/a",
        "const_invalid",
    ),
    "title_not_a_string": (
        _prop({"type": "string", "title": 3}),
        "/properties/a",
        "annotation_invalid",
    ),
}
for _bound in (
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minItems",
    "maxItems",
):
    STRICT_INELIGIBLE[f"bound_{_bound}"] = (
        _prop({"type": "string", _bound: 1}),
        f"/properties/a/{_bound}",
        "keyword_outside_grammar",
    )


@pytest.mark.parametrize(
    ("contract", "pointer", "rule"), STRICT_INELIGIBLE.values(), ids=STRICT_INELIGIBLE
)
def test_strict_response_violation_is_the_exact_pointer_and_rule(
    contract, pointer, rule
):
    before = copy.deepcopy(contract)
    assert first_strict_response_violation(contract) == (pointer, rule)
    assert contract == before


def test_strict_response_violation_is_the_first_in_document_order():
    contract = _closed(
        first={"type": "string", "minLength": 1},
        second={"type": "string", "pattern": "a"},
    )
    assert first_strict_response_violation(contract) == (
        "/properties/first/minLength",
        "keyword_outside_grammar",
    )


def test_strict_response_violation_escapes_property_names_in_the_pointer():
    contract = _closed(**{"~a/b": {"type": "string", "minLength": 1}})
    assert first_strict_response_violation(contract) == (
        "/properties/~0a~1b/minLength",
        "keyword_outside_grammar",
    )


def test_strict_response_violation_reads_property_names_as_data():
    contract = _closed(**{"type": {"type": "string", "pattern": "x"}})
    assert first_strict_response_violation(contract) == (
        "/properties/type/pattern",
        "keyword_outside_grammar",
    )


def test_strict_response_violation_fails_closed_on_a_contract_too_deep_to_walk():
    contract: dict[str, Any] = {"type": "string"}
    for _ in range(2000):
        contract = _closed(c=contract)
    unbounded = dataclasses.replace(
        COMMON_STRICT_SCHEMA_LIMITS, max_nesting_levels=10_000
    )
    violation = first_strict_response_violation(contract, unbounded)
    assert violation is not None and violation[1] == "contract_unreadable"
    assert first_strict_response_violation(contract) is not None


def test_strict_response_allowlist_stays_inside_the_grammar_safety_precondition():
    assert _STRICT_RESPONSE_KEYWORDS <= _COMMON_SCHEMA_KEYWORDS


# --- strict response: provider limits ---


def test_strict_limits_are_documented_openai_values_and_the_common_default():
    assert STRICT_SCHEMA_LIMITS_BY_PROVIDER["openai"] == StrictSchemaLimits(
        max_nesting_levels=10,
        max_properties=5000,
        max_enum_values=1000,
        enum_size_checked_above_values=250,
        max_enum_string_chars=15_000,
        max_total_string_chars=120_000,
    )
    assert COMMON_STRICT_SCHEMA_LIMITS == STRICT_SCHEMA_LIMITS_BY_PROVIDER["openai"]
    assert (
        strict_schema_limits_for("openai") is STRICT_SCHEMA_LIMITS_BY_PROVIDER["openai"]
    )
    assert strict_schema_limits_for("not-declared") is COMMON_STRICT_SCHEMA_LIMITS


def test_strict_common_limits_are_the_fieldwise_minimum_over_declared_providers():
    stricter = dataclasses.replace(
        STRICT_SCHEMA_LIMITS_BY_PROVIDER["openai"],
        max_nesting_levels=4,
        max_properties=9000,
    )
    common = strict_schema_limits._common_limits(
        {**STRICT_SCHEMA_LIMITS_BY_PROVIDER, "other": stricter}
    )
    assert common.max_nesting_levels == 4
    assert common.max_properties == 5000


def test_strict_a_declared_provider_limit_replaces_the_common_one():
    assert first_strict_response_violation(_nested_objects(3)) is None
    narrow = dataclasses.replace(COMMON_STRICT_SCHEMA_LIMITS, max_nesting_levels=2)
    assert first_strict_response_violation(_nested_objects(3), narrow) is not None


def test_strict_nesting_levels_10_are_eligible_and_11_are_not():
    assert first_strict_response_violation(_nested_objects(10)) is None
    violation = first_strict_response_violation(_nested_objects(11))
    assert violation is not None and violation[1] == "nesting_depth_exceeded"
    assert violation[0].count("/properties/child") == 10


def test_strict_an_array_counts_as_a_nesting_level():
    def chain(pairs: int, tail: dict[str, Any]) -> dict[str, Any]:
        contract = _closed(leaf=tail)
        for _ in range(pairs):
            contract = _closed(rows={"type": "array", "items": contract})
        return contract

    # Each pair is an array and an object: 4 pairs, a root object and an array of
    # strings are 10 levels; 5 pairs and a root object are 11.
    ten = chain(4, {"type": "array", "items": {"type": "string"}})
    assert first_strict_response_violation(ten) is None
    violation = first_strict_response_violation(chain(5, {"type": "string"}))
    assert violation is not None and violation[1] == "nesting_depth_exceeded"


def test_strict_properties_5000_are_eligible_and_5001_are_not():
    assert first_strict_response_violation(_strings(5000)) is None
    assert first_strict_response_violation(_strings(5001)) == (
        "",
        "property_count_exceeded",
    )


def test_strict_property_count_is_a_total_over_every_object():
    contract = _closed(a=_strings(2500, "x"), b=_strings(2500, "y"))
    assert first_strict_response_violation(contract) == (
        "/properties/b",
        "property_count_exceeded",
    )


def _enum_property(values: list[Any]) -> dict[str, Any]:
    return _closed(e={"type": "string", "enum": values})


def test_strict_enum_values_1000_are_eligible_and_1001_are_not():
    assert (
        first_strict_response_violation(_enum_property([f"v{i}" for i in range(1000)]))
        is None
    )
    assert first_strict_response_violation(
        _enum_property([f"v{i}" for i in range(1001)])
    ) == ("/properties/e", "enum_value_count_exceeded")


def test_strict_enum_value_count_is_a_total_over_every_enum():
    contract = _closed(
        **{
            name: {"type": "string", "enum": [f"{name}{i}" for i in range(400)]}
            for name in ("a", "b", "c")
        }
    )
    assert first_strict_response_violation(contract) == (
        "/properties/c",
        "enum_value_count_exceeded",
    )


def test_strict_a_large_enum_is_bound_by_its_own_string_size():
    within = [f"{i:03d}" + "x" * 56 for i in range(251)]  # 251 values, 59 chars
    over = [f"{i:03d}" + "x" * 57 for i in range(251)]  # 251 values, 60 chars
    assert first_strict_response_violation(_enum_property(within)) is None
    assert first_strict_response_violation(_enum_property(over)) == (
        "/properties/e",
        "enum_string_size_exceeded",
    )


def test_strict_an_enum_up_to_the_size_check_threshold_is_not_bound_by_string_size():
    values = [f"{i:03d}" + "x" * 60 for i in range(250)]  # 250 values, 63 chars
    assert first_strict_response_violation(_enum_property(values)) is None


def test_strict_total_string_size_120000_is_eligible_and_120001_is_not():
    def const_of(length: int) -> dict[str, Any]:
        return _closed(a={"type": "string", "const": "c" * length})

    assert first_strict_response_violation(const_of(119_999)) is None
    assert first_strict_response_violation(const_of(120_000)) == (
        "/properties/a",
        "string_size_exceeded",
    )


def test_strict_total_string_size_counts_property_names_and_enum_values():
    names = _closed(
        **{"n" * 60_000: {"type": "string"}, "m" * 60_001: {"type": "string"}}
    )
    assert first_strict_response_violation(names) == ("", "string_size_exceeded")
    enums = _closed(
        a={"type": "string", "enum": ["e" * 60_000]},
        b={"type": "string", "enum": ["e" * 60_000]},
    )
    assert first_strict_response_violation(enums) == (
        "/properties/b",
        "string_size_exceeded",
    )


def test_strict_an_enum_over_its_allowance_is_refused_before_it_is_hashed():
    class Spy(str):
        hashed = 0

        def __hash__(self) -> int:
            Spy.hashed += 1
            return str.__hash__(self)

    limits = dataclasses.replace(COMMON_STRICT_SCHEMA_LIMITS, max_enum_values=3)
    over = _enum_property([Spy(f"v{i}") for i in range(4)])
    assert first_strict_response_violation(over, limits) == (
        "/properties/e",
        "enum_value_count_exceeded",
    )
    assert Spy.hashed == 0
    within = _enum_property([Spy(f"v{i}") for i in range(3)])
    assert first_strict_response_violation(within, limits) is None
    assert Spy.hashed > 0


def test_strict_the_enum_allowance_is_what_earlier_enums_left():
    limits = dataclasses.replace(COMMON_STRICT_SCHEMA_LIMITS, max_enum_values=3)
    contract = _closed(
        a={"type": "string", "enum": ["a1", "a2"]},
        b={"type": "string", "enum": ["b1", "b2"]},
    )
    assert first_strict_response_violation(contract, limits) == (
        "/properties/b",
        "enum_value_count_exceeded",
    )
