from __future__ import annotations

import base64

from eneo.flows.http_transport.authored_config import (
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
from eneo.flows.variable_resolver import FlowVariableResolver


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


def test_json_template_with_invalid_json_falls_back_to_bytes() -> None:
    cfg = _config(body=HttpBody(mode=HttpBodyMode.JSON_TEMPLATE, template="not json"))
    result = compile_http_config(cfg, direction="output", method="POST")

    assert result.body == b"not json"
    assert result.json_body is None


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
    context = resolver.build_context_with_evidence(
        {"case_id": "A-17", "credential": "do-not-record"},
        [],
    )
    cfg = _config(
        url="https://example.org/{{ flow_input.case_id }}",
        auth=HttpAuthBearer(token="{{ flow_input.credential }}"),
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
                value="{{ flow_input.credential }}",
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
    assert result.headers["X-Secret"] == "do-not-record"
    assert [edge.binding_ref for edge in result.resolved_input_edges] == [
        "http.url:flow_input.case_id",
        "http.custom_headers[0].value:flow_input.case_id",
        "http.body:flow_input.case_id",
    ]
    assert {edge.source.selector.path for edge in result.resolved_input_edges} == {
        ("case_id",)
    }
    assert "credential" not in str(
        [edge.model_dump(mode="json") for edge in result.resolved_input_edges]
    )
