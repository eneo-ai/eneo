from types import SimpleNamespace

import httpx
import pytest

from eneo.mcp_servers.application import runtime_status as module


@pytest.mark.parametrize(
    "expected,actual,revision,other,warnings",
    [
        ("v2.3.0", "2.3.0", "a" * 40, "a" * 40, []),
        ("2.3.0", "2.3.1", "a" * 40, "a" * 40, ["version_mismatch"]),
        ("2.3.0", "2.3.0", "a" * 40, "b" * 40, ["revision_mismatch"]),
        ("DEV", "0.0.0-dev", "unknown", "unknown", ["unverified"]),
        ("2.3.0-dev", "2.3.0-dev", "unknown", "unknown", ["unverified"]),
        ("DEV", "0.0.0-dev", "a" * 40, "b" * 40, ["unverified", "revision_mismatch"]),
    ],
)
def test_version_warning_is_advisory(expected, actual, revision, other, warnings):
    assert module.compare_versions(expected, actual, revision, other) == warnings


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code,state",
    [(200, "ready"), (401, "unauthorized"), (404, "unverified"), (503, "unreachable")],
)
async def test_diagnostics_are_cached_and_bounded(monkeypatch, code, state):
    settings = SimpleNamespace(
        tool_runtime_url="http://tools:3010",
        tool_runtime_token="secret",
        app_version="2.3.0",
        app_revision="a" * 40,
    )
    monkeypatch.setattr(module, "get_settings", lambda: settings)
    monkeypatch.setattr(
        module, "file_reference_base_url", lambda _: "http://backend:8000"
    )
    monkeypatch.setattr(module, "_cache", None)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["authorization"] == "Bearer secret"
        return httpx.Response(
            code,
            json={
                "version": "2.3.0",
                "revision": "a" * 40,
                "confinement": {"files": True, "tcp": True},
                "execution": {"active": 1, "queued": 2},
                "file_origin": "reachable",
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **_: client)
    first = await module.runtime_status()
    second = await module.runtime_status()
    assert first.state == state
    assert first == second and first is not second
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_missing_configuration_does_not_probe(monkeypatch):
    monkeypatch.setattr(module, "_cache", None)
    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: SimpleNamespace(
            tool_runtime_url=None,
            tool_runtime_token=None,
            app_version="2.3.0",
            app_revision="unknown",
        ),
    )
    monkeypatch.setattr(module, "file_reference_base_url", lambda _: None)
    assert (await module.runtime_status()).state == "not_configured"


@pytest.mark.asyncio
async def test_timeout_is_advisory(monkeypatch):
    monkeypatch.setattr(module, "_cache", None)
    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: SimpleNamespace(
            tool_runtime_url="http://tools",
            tool_runtime_token="secret",
            app_version="2.3.0",
            app_revision="unknown",
        ),
    )
    monkeypatch.setattr(module, "file_reference_base_url", lambda _: None)

    def handler(request):
        raise httpx.ConnectTimeout("private diagnostic detail")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **_: client)
    result = await module.runtime_status()
    assert result.state == "unreachable"
    assert "private" not in result.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["not_allowed", "unreachable", "unknown"])
async def test_file_origin_and_confinement_warnings_are_additive(monkeypatch, origin):
    settings = SimpleNamespace(
        tool_runtime_url="http://tools:3010",
        tool_runtime_token="secret",
        app_version="2.3.0",
        app_revision="a" * 40,
    )
    monkeypatch.setattr(module, "get_settings", lambda: settings)
    monkeypatch.setattr(
        module, "file_reference_base_url", lambda _: "http://backend:8000"
    )
    monkeypatch.setattr(module, "_cache", None)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "version": "2.2.0",
                    "revision": "b" * 40,
                    "confinement": {"files": False, "tcp": False},
                    "execution": {"active": 0, "queued": 0},
                    "file_origin": origin,
                },
            )
        )
    )
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **_: client)
    result = await module.runtime_status()
    assert result.state == "ready"
    assert result.warnings == [
        "version_mismatch",
        "revision_mismatch",
        "confinement_unavailable",
        f"file_origin_{origin}",
    ]
