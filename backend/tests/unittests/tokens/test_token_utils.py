import base64
import io
import json
from unittest.mock import patch

import litellm
from PIL import Image

from eneo.tokens import token_utils
from eneo.tokens.token_utils import (
    _MAX_TOOL_SCHEMA_EXPANSION_CHARS,
    TokenCountSource,
    _tool_reserve_payload,
    count_image_tokens_from_blob,
    count_message_tokens,
    count_tokens,
    count_tool_tokens,
    log_token_count_drift,
    measure_message_token_delta,
    measure_message_tokens,
    measure_provider_input_reserve,
    measure_provider_input_tokens,
    measure_tool_tokens,
)


def _image_data_url(width: int, height: int) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (230, 230, 230)).save(
        buffer, format="JPEG", quality=85
    )
    encoded = base64.b64encode(buffer.getvalue()).decode()
    return f"data:image/jpeg;base64,{encoded}"


def _image_message(width: int, height: int) -> list[dict]:
    return [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": _image_data_url(width, height),
                        "detail": "high",
                    },
                }
            ],
        }
    ]


_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": "Generate an image based on a text prompt.",
            "parameters": {
                "type": "object",
                "properties": {"prompt": {"type": "string"}},
                "required": ["prompt"],
            },
        },
    }
]


def test_count_tokens_empty_text():
    assert count_tokens("") == 0


def test_count_message_tokens_includes_scaffolding_overhead():
    text = "hello world"
    assert count_message_tokens([{"role": "user", "content": text}]) > count_tokens(
        text
    )


def test_count_message_tokens_counts_image_blocks():
    base = count_message_tokens([{"role": "user", "content": "hi"}])
    with_image = count_message_tokens(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "hi"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,aGVsbG8="},
                    },
                ],
            }
        ]
    )
    assert with_image >= base + 85


def test_count_tool_tokens_positive():
    assert count_tool_tokens(_TOOLS) > 0


def test_count_tool_tokens_empty():
    assert count_tool_tokens([]) == 0


def _referencing_tool(definition: dict) -> list[dict]:
    """A tool whose three properties share one `$defs` entry."""
    return [
        {
            "type": "function",
            "function": {
                "name": "propose_flow",
                "parameters": {
                    "type": "object",
                    "$defs": {"shared": definition},
                    "properties": {
                        name: {"$ref": "#/$defs/shared"}
                        for name in ("first", "second", "third")
                    },
                    "required": ["first", "second", "third"],
                    "additionalProperties": False,
                },
            },
        }
    ]


def test_tool_reserve_charges_a_shared_definition_at_every_use_site():
    # A provider prices the expanded schema, so an enum behind one `$ref` is
    # paid for by each property that references it. Reserving only the
    # reference's own bytes under-reserved the measured Builder schema by
    # thousands of tokens.
    definition = {
        "type": "string",
        "enum": ["candidate_passages", "page_or_section", "excerpt_reference"],
    }
    referencing = _referencing_tool(definition)
    without_reference = [
        {
            "type": "function",
            "function": {
                "name": "propose_flow",
                "parameters": {
                    "type": "object",
                    "properties": dict.fromkeys(
                        ("first", "second", "third"), definition
                    ),
                    "required": ["first", "second", "third"],
                    "additionalProperties": False,
                },
            },
        }
    ]

    assert count_tool_tokens(referencing) > count_tool_tokens(without_reference)


def test_tool_reserve_is_never_below_the_litellm_estimate():
    # The estimate carries per-tool scaffolding the serialized schema does not,
    # and it is the larger reading for a flat tool with a long description. No
    # consumer may reserve less than it did before this became structural.
    catalogue = [
        {
            "type": "function",
            "function": {
                "name": "activate_skill",
                "description": "Load one Skill.\n"
                + "\n".join(f"- key_{index}: Skill {index}" for index in range(30)),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "skill_key": {
                            "type": "string",
                            "enum": [f"key_{index}" for index in range(30)],
                        }
                    },
                    "required": ["skill_key"],
                    "additionalProperties": False,
                },
            },
        }
    ]
    for tools in (_TOOLS, catalogue):
        estimate = litellm.token_counter(
            model="openai/gpt-4o",
            messages=[{"role": "user", "content": ""}],
            tools=tools,
        ) - litellm.token_counter(
            model="openai/gpt-4o", messages=[{"role": "user", "content": ""}]
        )
        assert count_tool_tokens(tools, "openai/gpt-4o") >= estimate


def test_tool_reserve_terminates_on_cyclic_references_and_still_charges_them():
    self_cycle = _referencing_tool(
        {
            "type": "object",
            "properties": {"child": {"$ref": "#/$defs/shared"}},
            "required": ["child"],
            "additionalProperties": False,
        }
    )
    mutual_cycle = [
        {
            "type": "function",
            "function": {
                "name": "propose_flow",
                "parameters": {
                    "type": "object",
                    "$defs": {
                        "left": {
                            "type": "object",
                            "properties": {"right": {"$ref": "#/$defs/right"}},
                            "required": ["right"],
                            "additionalProperties": False,
                        },
                        "right": {
                            "type": "object",
                            "properties": {"left": {"$ref": "#/$defs/left"}},
                            "required": ["left"],
                            "additionalProperties": False,
                        },
                    },
                    "properties": {"root": {"$ref": "#/$defs/left"}},
                    "required": ["root"],
                    "additionalProperties": False,
                },
            },
        }
    ]

    for tools in (self_cycle, mutual_cycle):
        measured = measure_tool_tokens(tools, "openai/gpt-4o")
        # An unresolved reference keeps its definition, so the cycle still costs
        # what it puts on the wire rather than silently disappearing.
        assert measured.source is TokenCountSource.LITELLM
        assert measured.tokens > count_tool_tokens(_TOOLS, "openai/gpt-4o")


def test_tool_reserve_declines_a_definition_reused_into_a_huge_payload():
    # Counting nodes bounded the shape and not the size: a large definition
    # reached through many references materialized hundreds of megabytes while
    # staying far under any node ceiling. MCP permits a 1 MiB definition.
    definition = {"type": "string", "description": "x" * 100_000}
    tools = [
        {
            "type": "function",
            "function": {
                "name": "propose_flow",
                "parameters": {
                    "type": "object",
                    "$defs": {"shared": definition},
                    "properties": {
                        f"property_{index}": {"$ref": "#/$defs/shared"}
                        for index in range(100)
                    },
                    "required": [f"property_{index}" for index in range(100)],
                    "additionalProperties": False,
                },
            },
        }
    ]

    measured = measure_tool_tokens(tools, "openai/gpt-4o")

    assert measured.source is TokenCountSource.FALLBACK_ESTIMATE
    assert measured.tokens > 1_000_000_000


def test_tool_reserve_keeps_a_reference_and_its_target_when_keys_collide():
    # Merging the target into the reference's own object let a sibling key
    # overwrite the target's value, so the definition's cost vanished from the
    # use site exactly where it was supposed to be counted.
    tools = [
        {
            "type": "function",
            "function": {
                "name": "propose_flow",
                "parameters": {
                    "type": "object",
                    "$defs": {
                        "shared": {
                            "type": "string",
                            "description": "TARGET-TEXT " * 20,
                        }
                    },
                    "properties": {
                        "value": {
                            "$ref": "#/$defs/shared",
                            "description": "SIBLING-TEXT " * 20,
                        }
                    },
                    "required": ["value"],
                    "additionalProperties": False,
                },
            },
        }
    ]

    payload = _tool_reserve_payload(tools)

    # Once in `$defs` and once written out at the use site, beside the sibling.
    assert payload.text.count("TARGET-TEXT") == 40
    assert payload.text.count("SIBLING-TEXT") == 20


def test_only_a_direct_definition_reference_is_priced():
    # The pointer grammar this counter supports is exactly `#/$defs/<name>`.
    # Reading `#/$defs/a/b` as a definition literally named "a/b" resolved a
    # different schema than a validator would, and `#`, an anchor or an
    # external document cannot be resolved here at all. Each must refuse.
    nested = {"type": "string", "description": "B" * 5_000}
    for pointer in (
        "#/$defs/outer/inner",
        "#",
        "#anchor",
        "https://example.invalid/shared.json#/$defs/shared",
    ):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "propose_flow",
                    "parameters": {
                        "type": "object",
                        "$defs": {
                            "outer": {"inner": nested},
                            "outer/inner": {"type": "string"},
                        },
                        "properties": {"value": {"$ref": pointer}},
                        "required": ["value"],
                        "additionalProperties": False,
                    },
                },
            }
        ]

        measured = measure_tool_tokens(tools, "openai/gpt-4o")

        assert measured.source is TokenCountSource.FALLBACK_ESTIMATE
        assert measured.tokens > 1_000_000_000


def test_a_refused_schema_stops_the_walk_instead_of_serializing_the_rest():
    # Once the answer is a refusal there is nothing left to measure, and a
    # catalogue may be tens of megabytes. The guard is bounded work, so count
    # the serializations rather than the seconds: elapsed time passes this on a
    # fast machine even when every remaining target is serialized again.
    definition = {"type": "string", "description": "C" * 20_000}

    def serializations_for(references: int) -> int:
        properties = {
            f"property_{index}": {"$ref": "#/$defs/shared"}
            for index in range(references)
        }
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "propose_flow",
                    "parameters": {
                        "type": "object",
                        "$defs": {"shared": definition},
                        # An unsupported reference decides the refusal before
                        # any of the supported ones are reached.
                        "properties": {"first": {"$ref": "#"}, **properties},
                        "required": ["first", *sorted(properties)],
                        "additionalProperties": False,
                    },
                },
            }
        ]
        with patch(
            "eneo.tokens.token_utils._serialized",
            wraps=token_utils._serialized,
        ) as serialized:
            payload = _tool_reserve_payload(tools)
        assert not payload.bounded
        return serialized.call_count

    assert serializations_for(900) == serializations_for(10)


def test_a_reference_this_counter_cannot_resolve_is_refused():
    # Pointers are read against the parameter object, as the strict-schema
    # owner and the provider do. Anything else local — a hoisted `$defs`, a
    # `#/definitions/` pointer, a name that is simply absent — would otherwise
    # be charged once instead of once per use, which is the whole defect.
    for pointer in ("#/$defs/missing", "#/definitions/shared"):
        tools = [
            {
                "type": "function",
                "$defs": {"shared": {"type": "string", "enum": ["ALPHA-KEY"]}},
                "function": {
                    "name": "propose_flow",
                    "parameters": {
                        "type": "object",
                        "properties": {"first": {"$ref": pointer}},
                        "required": ["first"],
                        "additionalProperties": False,
                    },
                },
            }
        ]

        measured = measure_tool_tokens(tools, "openai/gpt-4o")

        assert measured.source is TokenCountSource.FALLBACK_ESTIMATE
        assert measured.tokens > 1_000_000_000


def test_tool_reserve_counts_the_pointer_as_well_as_the_definition():
    # A pointer is bytes on the wire too, and a long definition name repeated
    # across properties is most of the payload. Replacing the pointer with its
    # target priced this roughly 22,000-character schema at a tenth of its
    # size; the same defect on a 20,000-character name cost ten times more.
    name = "n" * 2_000
    tools = [
        {
            "type": "function",
            "function": {
                "name": "propose_flow",
                "parameters": {
                    "type": "object",
                    "$defs": {name: {"type": "string"}},
                    "properties": {
                        f"property_{index}": {"$ref": f"#/$defs/{name}"}
                        for index in range(10)
                    },
                    "required": [f"property_{index}" for index in range(10)],
                    "additionalProperties": False,
                },
            },
        }
    ]

    payload = _tool_reserve_payload(tools)

    assert payload.bounded
    assert len(payload.text) >= len(
        json.dumps(tools, ensure_ascii=False, separators=(",", ":"))
    )


def test_a_percent_encoded_definition_name_costs_what_its_literal_does():
    # The pointer is a URI fragment holding a JSON Pointer. Reading it without
    # percent-decoding left the reference unexpanded and the definition charged
    # once rather than once per use.
    definition = {"type": "string", "enum": ["A" * 2_000]}

    def tools_referencing(pointer: str) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "propose_flow",
                    "parameters": {
                        "type": "object",
                        "$defs": {"space name": definition},
                        "properties": {
                            f"property_{index}": {"$ref": pointer}
                            for index in range(10)
                        },
                        "required": [f"property_{index}" for index in range(10)],
                        "additionalProperties": False,
                    },
                },
            }
        ]

    literal = count_tool_tokens(
        tools_referencing("#/$defs/space name"), "openai/gpt-4o"
    )
    encoded = count_tool_tokens(
        tools_referencing("#/$defs/space%20name"), "openai/gpt-4o"
    )

    assert encoded >= literal


def test_a_reference_chain_too_deep_to_follow_is_refused():
    # A chain deep enough to exhaust the interpreter's stack must answer with a
    # refusal rather than raise out of a token count.
    depth = 1_100
    definitions: dict[str, object] = {"level_0": {"type": "string"}}
    for level in range(1, depth):
        definitions[f"level_{level}"] = {"$ref": f"#/$defs/level_{level - 1}"}
    tools = [
        {
            "type": "function",
            "function": {
                "name": "propose_flow",
                "parameters": {
                    "type": "object",
                    "$defs": definitions,
                    "properties": {"root": {"$ref": f"#/$defs/level_{depth - 1}"}},
                    "required": ["root"],
                    "additionalProperties": False,
                },
            },
        }
    ]

    measured = measure_tool_tokens(tools, "openai/gpt-4o")

    assert measured.source is TokenCountSource.FALLBACK_ESTIMATE
    assert measured.tokens > 1_000_000_000


def test_the_expansion_ceiling_admits_what_fits_under_it():
    # The ceiling is a stated size, so a schema that expands to about half of
    # it must still be measured; only crossing it refuses.
    definition = {"type": "string", "description": "x" * 100_000}

    def tools_with(references: int) -> list[dict]:
        properties = {
            f"property_{index}": {"$ref": "#/$defs/shared"}
            for index in range(references)
        }
        return [
            {
                "type": "function",
                "function": {
                    "name": "propose_flow",
                    "parameters": {
                        "type": "object",
                        "$defs": {"shared": definition},
                        "properties": properties,
                        "required": sorted(properties),
                        "additionalProperties": False,
                    },
                },
            }
        ]

    under = _tool_reserve_payload(tools_with(20))
    over = _tool_reserve_payload(tools_with(100))

    assert under.bounded
    assert len(under.text) > _MAX_TOOL_SCHEMA_EXPANSION_CHARS // 4
    assert not over.bounded


def test_a_completed_reference_does_not_condemn_a_large_plain_catalogue():
    # Only material a reference introduces is bounded. A catalogue that merely
    # follows one small resolved reference is ordinary input, not amplification.
    referencing = _referencing_tool({"type": "string", "enum": ["alpha"]})
    catalogue = referencing + [
        {
            "type": "function",
            "function": {
                "name": f"tool_{index}",
                "description": "d" * 400,
                "parameters": {
                    "type": "object",
                    "properties": {
                        f"query_{inner}": {"type": "string", "description": "e" * 80}
                        for inner in range(60)
                    },
                    "required": [f"query_{inner}" for inner in range(60)],
                    "additionalProperties": False,
                },
            },
        }
        for index in range(256)
    ]

    measured = measure_tool_tokens(catalogue, "openai/gpt-4o")

    assert measured.source is TokenCountSource.LITELLM
    assert measured.tokens < 1_000_000


def test_the_reporting_fallback_prices_the_tools_as_written():
    # Reporting stands in for what the provider says it charged. Pricing the
    # expanded form here would inflate the usage recorded against a tenant
    # whenever a response omits its own count.
    tools = _referencing_tool({"type": "string", "description": "r" * 2_000})

    with patch(
        "eneo.tokens.token_utils.litellm.token_counter",
        side_effect=RuntimeError("boom"),
    ):
        report = measure_provider_input_tokens([], tools, "openai/gpt-4o")
        reserve = measure_tool_tokens(tools, "openai/gpt-4o")

    assert report.source is TokenCountSource.FALLBACK_ESTIMATE
    assert report.tokens < reserve.tokens


def test_tool_reserve_declines_a_schema_whose_expansion_cannot_be_bounded():
    # Definitions that reference each other unfold exponentially. The reserve
    # must not answer with a number any budget would accept.
    depth = 24
    definitions: dict[str, object] = {"level_0": {"type": "string"}}
    for level in range(1, depth):
        reference = {"$ref": f"#/$defs/level_{level - 1}"}
        definitions[f"level_{level}"] = {
            "type": "object",
            "properties": {"left": reference, "right": reference},
            "required": ["left", "right"],
            "additionalProperties": False,
        }
    tools = [
        {
            "type": "function",
            "function": {
                "name": "propose_flow",
                "parameters": {
                    "type": "object",
                    "$defs": definitions,
                    "properties": {"root": {"$ref": f"#/$defs/level_{depth - 1}"}},
                    "required": ["root"],
                    "additionalProperties": False,
                },
            },
        }
    ]

    measured = measure_tool_tokens(tools, "openai/gpt-4o")

    assert measured.source is TokenCountSource.FALLBACK_ESTIMATE
    # Larger than any context window, so every budget subtracting it refuses,
    # whether or not the caller inspects the source.
    assert measured.tokens > 1_000_000_000


def test_tool_reserve_fallback_stays_an_upper_bound_for_dense_scripts():
    # len // 4 under-counts anything that is not ASCII prose, and a reserve
    # built on it admits a request the provider then refuses.
    for text in (
        "公開情報の開示判断における候補箇所",
        "🚒🧯🔥🚨" * 12,
        "!@#$%^&*()" * 12,
    ):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "propose_flow",
                    "description": text,
                    "parameters": {
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                        "required": ["value"],
                        "additionalProperties": False,
                    },
                },
            }
        ]
        real = count_tool_tokens(tools, "openai/gpt-4o")
        with patch(
            "eneo.tokens.token_utils.litellm.token_counter",
            side_effect=RuntimeError("boom"),
        ):
            fallback = measure_tool_tokens(tools, "openai/gpt-4o")

        assert fallback.source is TokenCountSource.FALLBACK_ESTIMATE
        assert fallback.tokens >= real


def test_provider_input_reserve_bounds_both_halves_when_tokenizing_fails():
    messages = [{"role": "user", "content": "公開情報の開示判断における候補箇所"}]

    measured = measure_provider_input_reserve(messages, _TOOLS, "openai/gpt-4o")
    assert measured.source is TokenCountSource.LITELLM
    assert measured.tokens >= count_tool_tokens(_TOOLS, "openai/gpt-4o")

    with patch(
        "eneo.tokens.token_utils.litellm.token_counter",
        side_effect=RuntimeError("boom"),
    ):
        fallback = measure_provider_input_reserve(messages, _TOOLS, "openai/gpt-4o")

    assert fallback.source is TokenCountSource.FALLBACK_ESTIMATE
    assert fallback.tokens >= measured.tokens


def test_count_message_tokens_fallback_when_litellm_fails():
    messages = [
        {"role": "user", "content": "x" * 400},
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,a"}}
            ],
        },
    ]
    with patch(
        "eneo.tokens.token_utils.litellm.token_counter",
        side_effect=RuntimeError("boom"),
    ):
        tokens = count_message_tokens(messages)

    # len//4 for the text + flat image estimate + per-message overhead
    assert tokens == 100 + 4 + 1105 + 4


def test_count_message_tokens_fallback_counts_tool_call_identity_and_arguments():
    short_call = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call-short",
                    "type": "function",
                    "function": {"name": "propose_flow", "arguments": "{}"},
                }
            ],
        }
    ]
    long_call = [
        {
            **short_call[0],
            "tool_calls": [
                {
                    "id": "call-long",
                    "type": "function",
                    "function": {
                        "name": "propose_flow",
                        "arguments": "x" * 800,
                    },
                }
            ],
        }
    ]

    with patch(
        "eneo.tokens.token_utils.litellm.token_counter",
        side_effect=RuntimeError("boom"),
    ):
        short_tokens = count_message_tokens(short_call)
        long_tokens = count_message_tokens(long_call)

    assert long_tokens >= short_tokens + 200


def test_measure_message_tokens_reports_litellm_or_named_fallback_source():
    messages = [{"role": "system", "content": "System instructions"}]

    measured = measure_message_tokens(messages, "openai/gpt-4o")

    assert measured.tokens == count_message_tokens(messages, "openai/gpt-4o")
    assert measured.source is TokenCountSource.LITELLM

    with patch(
        "eneo.tokens.token_utils.litellm.token_counter",
        side_effect=RuntimeError("boom"),
    ):
        fallback = measure_message_tokens(messages, "openai/gpt-4o")

    assert fallback.tokens > 0
    assert fallback.source is TokenCountSource.FALLBACK_ESTIMATE


def test_measure_message_token_delta_recomputes_both_sides_with_one_counter():
    base = [{"role": "system", "content": "Base"}]
    composed = [{"role": "system", "content": "Base plus Skill"}]

    with (
        patch(
            "eneo.tokens.token_utils._measure_messages_with_litellm",
            side_effect=[20, RuntimeError("second count failed")],
        ),
        patch(
            "eneo.tokens.token_utils._fallback_message_tokens",
            side_effect=[4, 9],
        ) as fallback,
    ):
        measurement = measure_message_token_delta(
            base,
            composed,
            "anthropic/claude-sonnet-4",
        )

    assert measurement.tokens == 5
    assert measurement.source is TokenCountSource.FALLBACK_ESTIMATE
    assert [call.args[0] for call in fallback.call_args_list] == [base, composed]


def test_measure_message_token_delta_short_circuits_identical_messages():
    messages = [{"role": "system", "content": "Same"}]

    with patch("eneo.tokens.token_utils._measure_messages_with_litellm") as counter:
        measurement = measure_message_token_delta(
            messages,
            messages.copy(),
            "azure/gpt-4.1",
        )

    counter.assert_not_called()
    assert measurement.tokens == 0
    assert measurement.source is TokenCountSource.LITELLM


def test_measure_provider_input_tokens_counts_one_combined_provider_payload():
    messages = [{"role": "user", "content": "Question"}]
    with patch(
        "eneo.tokens.token_utils.litellm.token_counter",
        return_value=47,
    ) as counter:
        measurement = measure_provider_input_tokens(
            messages,
            _TOOLS,
            "openai/gpt-4o",
        )

    assert measurement.tokens == 47
    assert measurement.source is TokenCountSource.LITELLM
    counter.assert_called_once_with(
        model="openai/gpt-4o",
        messages=messages,
        tools=_TOOLS,
    )


def test_measure_provider_input_tokens_falls_back_for_the_whole_payload():
    with patch(
        "eneo.tokens.token_utils.litellm.token_counter",
        side_effect=RuntimeError("boom"),
    ) as counter:
        measurement = measure_provider_input_tokens(
            [{"role": "user", "content": "Question"}],
            _TOOLS,
            "custom/unknown",
        )

    assert measurement.tokens > 0
    assert measurement.source is TokenCountSource.FALLBACK_ESTIMATE
    assert counter.call_count == 1


def test_count_tool_tokens_fallback_when_litellm_fails():
    with patch(
        "eneo.tokens.token_utils.litellm.token_counter",
        side_effect=RuntimeError("boom"),
    ):
        assert count_tool_tokens(_TOOLS) > 0


def _image_blob(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (230, 230, 230)).save(
        buffer, format="JPEG", quality=85
    )
    return buffer.getvalue()


def test_count_image_tokens_from_blob_uses_provider_formula():
    blob = _image_blob(2048, 1024)
    assert count_image_tokens_from_blob(blob, "openai/gpt-4o") == 1105
    assert (
        count_image_tokens_from_blob(blob, "anthropic/claude-3-5-haiku-20241022")
        == 1568
    )


def test_count_image_tokens_from_blob_falls_back_on_unreadable_data():
    assert count_image_tokens_from_blob(b"not an image") == 1105
    assert count_image_tokens_from_blob(None) == 1105


def test_drift_logging_warns_above_threshold(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="eneo.tokens.token_utils"):
        log_token_count_drift("openai/gpt-4o", predicted=1000, actual=1500)

    assert any("Token count drift" in r.message for r in caplog.records)


def test_drift_logging_silent_within_threshold(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="eneo.tokens.token_utils"):
        log_token_count_drift("openai/gpt-4o", predicted=1000, actual=1100)
        log_token_count_drift("openai/gpt-4o", predicted=None, actual=1100)
        log_token_count_drift("openai/gpt-4o", predicted=1000, actual=None)
        log_token_count_drift("openai/gpt-4o", predicted=0, actual=0)

    assert not caplog.records


def test_count_message_tokens_prices_images_by_provider_formula():
    # Each provider has its own documented image cost: OpenAI's tile formula
    # gives 1105 for 2048x1024, Anthropic's patch formula 1568 (capped).
    blank = [{"role": "user", "content": ""}]
    message = _image_message(2048, 1024)

    anthropic_delta = count_message_tokens(
        message, "anthropic/claude-3-5-haiku-20241022"
    ) - count_message_tokens(blank, "anthropic/claude-3-5-haiku-20241022")
    openai_delta = count_message_tokens(
        message, "openai/gpt-4o"
    ) - count_message_tokens(blank, "openai/gpt-4o")

    assert anthropic_delta == 1568
    assert openai_delta == 1105
