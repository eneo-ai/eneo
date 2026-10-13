"""The host owns the CSP for served app views: omitted declarations stay at
restrictive defaults, declared domains are threaded into exactly their
directive, and anything that is not a bare http(s) origin is dropped."""

from eneo.mcp_apps.domain.csp import build_app_csp


def _directives(csp: str) -> dict[str, str]:
    result = {}
    for directive in csp.split("; "):
        name, _, value = directive.partition(" ")
        result[name] = value
    return result


def test_empty_declaration_is_fully_restrictive():
    d = _directives(build_app_csp(None))

    # The response contains a trusted proxy; server HTML goes in its opaque
    # child. It cannot be framed without the configured Eneo origin.
    assert d["sandbox"] == "allow-scripts allow-same-origin"
    assert d["default-src"] == "'none'"
    assert d["script-src"] == "'self' 'unsafe-inline'"
    assert d["style-src"] == "'self' 'unsafe-inline'"
    assert d["img-src"] == "'self' data:"
    assert d["connect-src"] == "'none'"
    assert d["frame-src"] == "'none'"
    assert d["base-uri"] == "'self'"
    assert d["form-action"] == "'none'"
    assert d["frame-ancestors"] == "'none'"


def test_declared_domains_thread_into_their_directives():
    d = _directives(
        build_app_csp(
            {
                "resourceDomains": ["https://cdn.example.com"],
                "connectDomains": ["https://api.example.com:8443"],
                "frameDomains": ["https://embed.example.com"],
                "baseUriDomains": ["https://base.example.com"],
            }
        )
    )

    assert d["script-src"] == "'self' 'unsafe-inline' https://cdn.example.com"
    assert d["img-src"] == "'self' data: https://cdn.example.com"
    assert d["font-src"] == "'self' https://cdn.example.com"
    assert d["connect-src"] == "https://api.example.com:8443"
    assert (
        d["frame-src"] == "'none'"
    )  # App declarations cannot widen navigation of the child.
    assert d["base-uri"] == "https://base.example.com"


def test_invalid_entries_are_dropped_never_widened():
    d = _directives(
        build_app_csp(
            {
                "connectDomains": [
                    "https://ok.example",
                    "*",
                    "https://evil.example/path",
                    "javascript:alert(1)",
                    "https://evil.example?q=1",
                    "data:text/html",
                    42,
                ],
                "frameDomains": "not-a-list",
            }
        )
    )

    assert d["connect-src"] == "https://ok.example"
    assert d["frame-src"] == "'none'"


def test_frame_ancestors_pins_the_embedding_origin():
    d = _directives(build_app_csp(None, frame_ancestors="https://eneo.example"))

    assert d["frame-ancestors"] == "https://eneo.example"
