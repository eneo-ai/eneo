from __future__ import annotations

import base64
import math

import pytest

from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.http_transport.authored_config import (
    SECRET_SENTINEL,
    CustomHeader,
    HttpAuthApiKey,
    HttpAuthBasicAuth,
    HttpAuthBearer,
    HttpAuthNone,
    HttpAuthoredConfig,
    HttpBody,
    HttpBodyMode,
)
from eneo.flows.http_transport.compiler import compile_http_config
from eneo.flows.http_transport.errors import HttpRenderedBodyNotJsonError
from eneo.flows.variable_resolver import FlowVariableResolver, iter_template_expressions
from eneo.main.exceptions import TypedIOValidationException


def _config(
    *,
    url: str = "https://example.org/api",
    auth=None,
    body: HttpBody | None = None,
    custom_headers: list[CustomHeader] | None = None,
    timeout_seconds: int = 30,
) -> HttpAuthoredConfig:
    return HttpAuthoredConfig(
        url=url,
        auth=auth or HttpAuthNone(),
        body=body or HttpBody(mode=HttpBodyMode.AUTO),
        custom_headers=custom_headers or [],
        timeout_seconds=timeout_seconds,
    )


# --- Auth header compilation ---


def test_bearer_auth_produces_authorization_header() -> None:
    cfg = _config(auth=HttpAuthBearer(token="tok-123"))
    result = compile_http_config(cfg, direction="output", method="POST")

    assert result.headers["Authorization"] == "Bearer tok-123"


def test_secret_sentinel_fails_closed_during_compilation() -> None:
    cfg = _config(auth=HttpAuthBearer(token=SECRET_SENTINEL))

    with pytest.raises(
        TypedIOValidationException,
        match="server-side HTTP secret resolution defect",
    ) as exc:
        compile_http_config(cfg, direction="output", method="POST")

    assert exc.value.code == "typed_io_http_invalid_config"


def test_api_key_auth_produces_custom_header() -> None:
    cfg = _config(auth=HttpAuthApiKey(header_name="X-My-Key", key="secret-key"))
    result = compile_http_config(cfg, direction="output", method="POST")

    assert result.headers["X-My-Key"] == "secret-key"
    assert "Authorization" not in result.headers


def test_basic_auth_produces_base64_authorization_header() -> None:
    cfg = _config(auth=HttpAuthBasicAuth(username="alice", password="pass"))
    result = compile_http_config(cfg, direction="output", method="POST")

    expected = base64.b64encode(b"alice:pass").decode()
    assert result.headers["Authorization"] == f"Basic {expected}"


def test_no_auth_produces_no_auth_headers() -> None:
    cfg = _config(auth=HttpAuthNone())
    result = compile_http_config(cfg, direction="output", method="POST")

    assert "Authorization" not in result.headers


# --- Custom headers ---


def test_custom_header_without_a_name_is_left_out() -> None:
    cfg = _config(
        custom_headers=[
            CustomHeader(name="", value="", secret=False),
            CustomHeader(name="  ", value="val", secret=True),
            CustomHeader(name="X-Custom", value="val1", secret=False),
        ]
    )
    result = compile_http_config(cfg, direction="output", method="POST")

    assert result.headers["X-Custom"] == "val1"
    assert all(name.strip() for name in result.headers)


def test_custom_headers_included_in_result() -> None:
    headers = [
        CustomHeader(name="X-Custom", value="val1", secret=False),
        CustomHeader(name="X-Secret", value="val2", secret=True),
    ]
    cfg = _config(custom_headers=headers)
    result = compile_http_config(cfg, direction="output", method="POST")

    assert result.headers["X-Custom"] == "val1"
    assert result.headers["X-Secret"] == "val2"


# --- Body modes ---


def test_auto_body_returns_none() -> None:
    cfg = _config(body=HttpBody(mode=HttpBodyMode.AUTO))
    result = compile_http_config(cfg, direction="output", method="POST")

    assert result.body is None
    assert result.json_body is None


def test_json_template_body_parses_json() -> None:
    cfg = _config(
        body=HttpBody(mode=HttpBodyMode.JSON_TEMPLATE, template='{"key": "val"}')
    )
    result = compile_http_config(cfg, direction="output", method="POST")

    assert result.json_body == {"key": "val"}
    assert result.body is None


def test_text_template_body_returns_bytes() -> None:
    cfg = _config(
        body=HttpBody(mode=HttpBodyMode.TEXT_TEMPLATE, template="hello world")
    )
    result = compile_http_config(cfg, direction="output", method="POST")

    assert result.body == b"hello world"
    assert result.json_body is None


def test_none_body_mode_returns_none() -> None:
    cfg = _config(body=HttpBody(mode=HttpBodyMode.NONE))
    result = compile_http_config(cfg, direction="output", method="POST")

    assert result.body is None
    assert result.json_body is None


def test_json_template_with_none_template_returns_none() -> None:
    cfg = _config(body=HttpBody(mode=HttpBodyMode.JSON_TEMPLATE, template=None))
    result = compile_http_config(cfg, direction="output", method="POST")

    assert result.body is None
    assert result.json_body is None


def _compile_json_body(template: str, flow_input: dict[str, object]):
    resolver = FlowVariableResolver()
    return compile_http_config(
        _config(body=HttpBody(mode=HttpBodyMode.JSON_TEMPLATE, template=template)),
        direction="output",
        method="POST",
        variables=resolver.build_context(flow_input, []),
        interpolate=resolver.interpolate,
        resolve_value=resolver.resolve_value,
    )


def test_json_template_carries_text_of_many_lines_exactly() -> None:
    transcript = 'Anna: "Vi väljer A."\nErik: Ja\\nej,\ttack.\n{{ flow_input.x }}'

    result = _compile_json_body(
        '{"title": "Möte", "files": [{"name": "a.md", '
        '"content": "{{ flow_input.transcript }}"}]}',
        {"transcript": transcript},
    )

    assert result.json_body == {
        "title": "Möte",
        "files": [{"name": "a.md", "content": transcript}],
    }
    assert result.body is None


def test_json_template_text_cannot_add_to_the_structure() -> None:
    text = 'x", "role": "admin", "note": "y'

    result = _compile_json_body(
        '{"days": {{ flow_input.days }}, "note": "{{ flow_input.note }}"}',
        {"days": 3, "note": text},
    )

    assert result.json_body == {"days": 3, "note": text}


def test_json_template_reference_in_quotes_stays_the_text_it_was() -> None:
    result = _compile_json_body(
        '{"tags": "{{ flow_input.tags }}", "days": "{{ flow_input.days }}"}',
        {"tags": ["a", "b"], "days": 3},
    )

    assert result.json_body == {"tags": "a, b", "days": "3"}


@pytest.mark.parametrize(
    "value",
    [
        {"schemaVersion": 1, "title": "Skiss"},
        ["a", "b"],
        {"shapes": [{"id": "n1", "text": 'rad "1"\nrad 2'}]},
        3,
        2.5,
        True,
        None,
    ],
)
def test_json_template_reference_outside_quotes_keeps_its_json_type(
    value: object,
) -> None:
    result = _compile_json_body(
        '{"canvas": {{ flow_input.canvas }}, "note": "{{ flow_input.note }}"}',
        {"canvas": value, "note": "rad 1\nrad 2"},
    )

    assert result.json_body == {"canvas": value, "note": "rad 1\nrad 2"}


def test_json_template_takes_json_text_outside_quotes_as_its_value() -> None:
    result = _compile_json_body("{{ flow_input.answer }}", {"answer": '{"a": [1, 2]}'})

    assert result.json_body == {"a": [1, 2]}


def test_json_template_text_outside_quotes_fills_one_value_only() -> None:
    with pytest.raises(HttpRenderedBodyNotJsonError):
        _compile_json_body(
            '{"days": {{ flow_input.days }}}',
            {"days": '3, "role": "admin"'},
        )


@pytest.mark.parametrize(
    "template",
    [
        '{"n": 1{{ flow_input.a }}}',
        '{"n": -{{ flow_input.a }}}',
        '{"n": 1.{{ flow_input.a }}}',
        '{"n": {{ flow_input.a }}{{ flow_input.a }}}',
        '{"n": {{ flow_input.a }}0}',
    ],
)
def test_json_template_reference_is_never_part_of_a_number(template: str) -> None:
    with pytest.raises(HttpRenderedBodyNotJsonError):
        _compile_json_body(template, {"a": 2})


@pytest.mark.parametrize("escape", ["\\u000", "\\u", "\\u00", "\\"])
def test_json_template_escape_cannot_take_the_filled_text(escape: str) -> None:
    with pytest.raises(HttpRenderedBodyNotJsonError):
        _compile_json_body('{"note": "' + escape + '{{ flow_input.a }}"}', {"a": "a"})


def test_json_template_finished_escape_leaves_the_filled_text_alone() -> None:
    result = _compile_json_body(r'{"note": "\u000a\\{{ flow_input.a }}"}', {"a": "a"})

    assert result.json_body == {"note": "\n\\a"}


@pytest.mark.parametrize(
    ("template", "flow_input"),
    [
        ('{"n": {{ flow_input.a }}}', {"a": math.nan}),
        ('{"n": [{"m": {{ flow_input.a }}}]}', {"a": math.inf}),
        ('{"n": {{ flow_input.a }}}', {"a": "1e999"}),
        ('{"n": {{ flow_input.a }}}', {"a": "NaN"}),
        ('{"n": {{ flow_input.a }}}', {"a": '{"m": NaN, "m": 0}'}),
        ('{"n": {{ flow_input.a }}}', {"a": '{"m": 1e999, "m": 0}'}),
        ('{"n": {{ flow_input.a }}}', {"a": "[" * 100_000}),
        ('{"n": "{{ flow_input.a }}", "m": 1e999}', {"a": "x"}),
        ('{"n": -Infinity, "m": "{{ flow_input.a }}"}', {"a": "x"}),
    ],
)
def test_json_template_refuses_what_json_cannot_carry(
    template: str, flow_input: dict[str, object]
) -> None:
    with pytest.raises(HttpRenderedBodyNotJsonError):
        _compile_json_body(template, flow_input)


def test_json_template_null_text_outside_quotes_is_a_null_value() -> None:
    result = _compile_json_body('{"n": {{ flow_input.a }}}', {"a": "null"})

    assert result.json_body == {"n": None}


def test_json_template_text_saying_nan_stays_text() -> None:
    result = _compile_json_body('{"note": "{{ flow_input.a }}"}', {"a": "NaN"})

    assert result.json_body == {"note": "NaN"}


def test_json_template_leaves_an_escaped_brace_as_literal_text() -> None:
    result = _compile_json_body(
        '{"note": "\\u007b\\u007b flow_input.secret \\u007d\\u007d"}',
        {"secret": "hemligt"},
    )

    assert result.json_body == {"note": "{{ flow_input.secret }}"}


def test_json_template_records_each_read_as_a_body_read() -> None:
    resolver = FlowVariableResolver()
    result = compile_http_config(
        _config(
            body=HttpBody(
                mode=HttpBodyMode.JSON_TEMPLATE,
                template=(
                    '{"{{ flow_input.key }}": ["{{ flow_input.key }}", '
                    "{{ flow_input.count }}]}"
                ),
            )
        ),
        direction="input",
        method="POST",
        variables=resolver.build_context_with_evidence({"key": "a", "count": 1}, []),
        interpolate=resolver.interpolate,
        interpolate_with_evidence=resolver.interpolate_with_evidence,
        resolve_value=resolver.resolve_value,
    )

    assert result.json_body == {"a": ["a", 1]}
    assert sorted(edge.binding_ref for edge in result.resolved_input_edges) == [
        "http.body:flow_input.count",
        "http.body:flow_input.key",
    ]


@pytest.mark.parametrize(
    ("template", "flow_input"),
    [
        ("not json", {}),
        ("null", {}),
        ('{"note": {{ flow_input.text }}}', {"text": "personnummer 19000101"}),
        ('{"note": "\\{{ flow_input.text }}"}', {"text": "personnummer 19000101"}),
        ("{{ flow_input.text }}", {"text": "null"}),
    ],
)
def test_json_template_never_sends_a_body_that_is_not_json(
    template: str, flow_input: dict[str, object]
) -> None:
    with pytest.raises(HttpRenderedBodyNotJsonError) as caught:
        _compile_json_body(template, flow_input)

    assert caught.value.code == FlowApiErrorCode.TYPED_IO_HTTP_INVALID_CONFIG.value
    assert "19000101" not in str(caught.value)
    assert caught.value.__cause__ is None


# --- URL interpolation ---


def test_url_interpolation_with_interpolate_fn() -> None:
    cfg = _config(url="https://example.org/{{path}}")

    def interpolate(template: str, ctx: dict) -> str:
        return template.replace("{{path}}", ctx["path"])

    result = compile_http_config(
        cfg,
        direction="output",
        method="POST",
        variables={"path": "items"},
        interpolate=interpolate,
    )

    assert result.url == "https://example.org/items"


def test_interpolation_runs_with_empty_variables_context() -> None:
    cfg = _config(url="https://example.org/{{path}}")
    calls: list[object] = []

    def interpolate(template: str, ctx: object) -> str:
        calls.append(ctx)
        return template.replace("{{path}}", "items")

    result = compile_http_config(
        cfg,
        direction="output",
        method="POST",
        variables={},
        interpolate=interpolate,
    )

    assert result.url == "https://example.org/items"
    assert calls == [{}]


def test_url_unchanged_without_interpolate_fn() -> None:
    cfg = _config(url="https://example.org/{{path}}")
    result = compile_http_config(cfg, direction="output", method="POST")

    assert result.url == "https://example.org/{{path}}"


# --- Timeout ---


def test_timeout_from_config_is_used() -> None:
    cfg = _config(timeout_seconds=60)
    result = compile_http_config(cfg, direction="output", method="POST")

    assert result.timeout == 60.0


# --- Method passthrough ---


def test_method_is_passed_through() -> None:
    cfg = _config()
    result = compile_http_config(cfg, direction="output", method="GET")

    assert result.method == "GET"


def test_input_evidence_tracks_url_and_body_but_never_credentials() -> None:
    resolver = FlowVariableResolver()
    context = resolver.build_context_with_evidence({"case_id": "A-17"}, [])
    cfg = _config(
        url="https://example.org/{{ flow_input.case_id }}",
        auth=HttpAuthBearer(token="do-not-record"),
        body=HttpBody(
            mode=HttpBodyMode.JSON_TEMPLATE,
            template='{"case_id":"{{ flow_input.case_id }}"}',
        ),
        custom_headers=[
            CustomHeader(
                name="X-Case-Id",
                value="{{ flow_input.case_id }}",
                secret=False,
            ),
            CustomHeader(
                name="X-Secret",
                value="do-not-record-either",
                secret=True,
            ),
        ],
    )

    result = compile_http_config(
        cfg,
        direction="input",
        method="GET",
        variables=context,
        interpolate=resolver.interpolate,
        interpolate_with_evidence=resolver.interpolate_with_evidence,
    )

    assert result.url == "https://example.org/A-17"
    assert result.headers["Authorization"] == "Bearer do-not-record"
    assert result.headers["X-Case-Id"] == "A-17"
    assert result.headers["X-Secret"] == "do-not-record-either"
    assert [edge.binding_ref for edge in result.resolved_input_edges] == [
        "http.url:flow_input.case_id",
        "http.custom_headers[0].value:flow_input.case_id",
        "http.body:flow_input.case_id",
    ]
    assert {edge.source.selector.path for edge in result.resolved_input_edges} == {
        ("case_id",)
    }
    assert "do-not-record" not in str(
        [edge.model_dump(mode="json") for edge in result.resolved_input_edges]
    )


# --- The templates the compiler interpolates ---


def _interpolated_by_the_compiler(cfg: HttpAuthoredConfig) -> list[str]:
    seen: list[str] = []

    def record(template: str, _context: dict[str, object]) -> str:
        seen.append(template)
        return template

    compile_http_config(cfg, direction="input", method="GET", interpolate=record)
    return seen


@pytest.mark.parametrize(
    "cfg",
    [
        pytest.param(_config(url="u/{{ a }}"), id="url-only"),
        pytest.param(
            _config(auth=HttpAuthBearer(token="bearer-{single}-{{ open")),
            id="bearer-token-is-literal",
        ),
        pytest.param(
            _config(auth=HttpAuthApiKey(header_name="X-{{ c }}", key="literal-key")),
            id="api-key",
        ),
        pytest.param(
            _config(
                auth=HttpAuthBasicAuth(username="user {{ e }}", password="literal")
            ),
            id="basic-auth",
        ),
        pytest.param(
            _config(
                custom_headers=[
                    CustomHeader(name="X-{{ g }}", value="plain {{ h }}"),
                    CustomHeader(name="X-S", value="literal", secret=True),
                ]
            ),
            id="custom-headers-name-is-not-a-template",
        ),
        pytest.param(
            _config(
                body=HttpBody(
                    mode=HttpBodyMode.JSON_TEMPLATE, template='{"j": "{{ j }}"}'
                )
            ),
            id="json-body",
        ),
        pytest.param(
            _config(body=HttpBody(mode=HttpBodyMode.TEXT_TEMPLATE, template="{{ k }}")),
            id="text-body",
        ),
        pytest.param(
            _config(body=HttpBody(mode=HttpBodyMode.TEXT_TEMPLATE)),
            id="body-without-template",
        ),
        pytest.param(
            _config(body=HttpBody(mode=HttpBodyMode.AUTO, template="{{ l }}")),
            id="auto-body-ignores-template",
        ),
        pytest.param(
            _config(body=HttpBody(mode=HttpBodyMode.NONE, template="{{ m }}")),
            id="no-body-ignores-template",
        ),
    ],
)
def test_interpolated_templates_are_exactly_what_the_compiler_interpolates(
    cfg: HttpAuthoredConfig,
) -> None:
    assert sorted(
        expression
        for _, text in cfg.interpolated_template_sites()
        for expression in iter_template_expressions(text)
    ) == sorted(
        expression
        for text in _interpolated_by_the_compiler(cfg)
        for expression in iter_template_expressions(text)
    )


def test_interpolated_templates_skip_a_stored_secret_it_cannot_read() -> None:
    cfg = _config(
        auth=HttpAuthBearer(token=SECRET_SENTINEL),
        custom_headers=[
            CustomHeader(name="X-S", value=SECRET_SENTINEL, secret=True),
        ],
    )

    assert cfg.interpolated_template_sites() == [(("url",), "https://example.org/api")]


# --- A credential is a literal, never a template ---

_CREDENTIAL_TEMPLATES = [
    pytest.param(
        _config(auth=HttpAuthBearer(token="{{ step_1.output.text }}")),
        "auth.token",
        id="bearer-token",
    ),
    pytest.param(
        _config(auth=HttpAuthApiKey(header_name="X-Key", key="k-{{ flow_input.k }}")),
        "auth.key",
        id="api-key",
    ),
    pytest.param(
        _config(auth=HttpAuthBasicAuth(username="u", password="{{ föregående_steg }}")),
        "auth.password",
        id="basic-password",
    ),
    pytest.param(
        _config(
            custom_headers=[
                CustomHeader(name="X-Open", value="plain"),
                CustomHeader(name="X-S", value="{{ step_2.status }}", secret=True),
            ]
        ),
        "custom_headers[1].value",
        id="secret-header-value",
    ),
]


@pytest.mark.parametrize(("cfg", "field"), _CREDENTIAL_TEMPLATES)
def test_compilation_refuses_a_template_in_a_credential(
    cfg: HttpAuthoredConfig, field: str
) -> None:
    seen: list[str] = []

    def record(template: str, _context: dict[str, object]) -> str:
        seen.append(template)
        return template

    with pytest.raises(TypedIOValidationException) as exc:
        compile_http_config(cfg, direction="output", method="POST", interpolate=record)

    assert exc.value.code == "typed_io_http_invalid_config"
    assert field in str(exc.value)
    assert "{{" not in str(exc.value)
    # Refused before any interpolation could put run data into a credential.
    assert not any("{{" in template for template in seen)


def test_a_literal_credential_reaches_the_request_unchanged() -> None:
    cfg = _config(
        auth=HttpAuthApiKey(header_name="X-{{ name }}", key="{single}-and-{{ open"),
        custom_headers=[
            CustomHeader(name="X-S", value="s3cr{et}", secret=True),
            CustomHeader(name="X-P", value="plain-{{ name }}"),
        ],
    )

    result = compile_http_config(
        cfg,
        direction="output",
        method="POST",
        interpolate=lambda template, _ctx: template.replace("{{ name }}", "filled"),
    )

    assert result.headers["X-filled"] == "{single}-and-{{ open"
    assert result.headers["X-S"] == "s3cr{et}"
    assert result.headers["X-P"] == "plain-filled"
