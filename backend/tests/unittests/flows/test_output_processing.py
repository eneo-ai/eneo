"""Tests for eneo.flows.output_processing — pure function module."""

from __future__ import annotations

import tracemalloc

import pytest
from referencing import Registry

from eneo.flows.flow_run_error import FlowRunContractViolation
from eneo.flows.output_processing import (
    _contract_named_pointer,
    compile_validators,
    conform_keys_to_schema,
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
