"""Which call checks a provider's connection, and what its answer means."""

import logging
from collections.abc import Callable

import httpx
import pytest

from eneo.model_providers.domain.connection_check import (
    ConnectionCheckError,
    ConnectionCheckStatus,
)
from eneo.model_providers.domain.provider_api import (
    AZURE_MODELS_API_VERSION,
    ProviderRequest,
    configured_endpoint,
    connection_check_request,
    connection_check_supported,
    models_list_request,
)
from eneo.model_providers.infrastructure import provider_connection_probe
from eneo.model_providers.infrastructure.provider_connection_probe import (
    probe_connection,
)

KEY = "sk-live-secret-1234"


class TestConnectionCheckRequest:
    def test_openai_lists_models_with_a_bearer_key(self) -> None:
        request = connection_check_request("openai", KEY, "")

        assert request is not None
        assert request.url == "https://api.openai.com/v1/models"
        assert request.headers == {"Authorization": f"Bearer {KEY}"}

    def test_anthropic_uses_its_own_key_header(self) -> None:
        request = connection_check_request("anthropic", KEY, "")

        assert request is not None
        assert request.url == "https://api.anthropic.com/v1/models"
        assert request.headers["x-api-key"] == KEY
        assert "Authorization" not in request.headers

    def test_a_configured_endpoint_wins_like_the_model_picker(self) -> None:
        request = connection_check_request(
            "hosted_vllm", KEY, "https://llm.example.se/v1/"
        )

        assert request == models_list_request(
            "hosted_vllm", KEY, "https://llm.example.se/v1/"
        )
        assert request is not None
        assert request.url == "https://llm.example.se/v1/models"

    def test_azure_lists_models_on_a_pinned_api_version(self) -> None:
        request = connection_check_request(
            "azure", KEY, "https://kommun.openai.azure.com/"
        )

        assert request is not None
        assert request.url == (
            "https://kommun.openai.azure.com/openai/models"
            f"?api-version={AZURE_MODELS_API_VERSION}"
        )
        assert request.headers == {"api-key": KEY}
        # The model picker still skips Azure: its list is the whole region.
        assert models_list_request("azure", KEY, "https://x.openai.azure.com") is None

    def test_gemini_sends_the_key_in_a_header_and_counts_400_as_refused(
        self,
    ) -> None:
        request = connection_check_request("gemini", KEY, "")

        assert request is not None
        assert KEY not in request.url
        assert request.headers == {"x-goog-api-key": KEY}
        assert 400 in request.key_rejected_statuses

    def test_hosted_apis_without_an_endpoint_setting(self) -> None:
        request = connection_check_request("mistral", KEY, "")

        assert request is not None
        assert request.url == "https://api.mistral.ai/v1/models"
        # The picker keeps LiteLLM's static catalog for them.
        assert models_list_request("mistral", KEY, "") is None

    def test_unknown_types_need_an_endpoint(self) -> None:
        assert connection_check_request("perplexity", KEY, "") is None
        assert connection_check_request("azure", KEY, "") is None
        assert not connection_check_supported("perplexity", "")
        assert connection_check_supported("perplexity", "https://llm.example.se")
        assert connection_check_supported("openai", "")

    def test_configured_endpoint_ignores_blank_and_non_text_values(self) -> None:
        assert configured_endpoint({"endpoint": "  https://x.se  "}) == "https://x.se"
        assert configured_endpoint({"endpoint": None}) == ""
        assert configured_endpoint({"endpoint": 42}) == ""
        assert configured_endpoint({}) == ""


Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def respond(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[Handler], list[httpx.Request]]:
    """Route the probe's HTTP client to a handler; returns the requests sent."""

    def install(handler: Handler) -> list[httpx.Request]:
        sent: list[httpx.Request] = []

        def record(request: httpx.Request) -> httpx.Response:
            sent.append(request)
            return handler(request)

        monkeypatch.setattr(
            provider_connection_probe,
            "_http_client",
            lambda: httpx.AsyncClient(transport=httpx.MockTransport(record)),
        )
        return sent

    return install


def _openai() -> ProviderRequest:
    request = connection_check_request("openai", KEY, "")
    assert request is not None
    return request


class TestProbeConnection:
    async def test_2xx_is_ok_and_the_key_goes_only_in_the_header(self, respond) -> None:
        sent = respond(lambda request: httpx.Response(200, json={"data": []}))

        check = await probe_connection(_openai(), provider_label="p (openai)")

        assert check.status is ConnectionCheckStatus.OK
        assert check.error is None
        assert check.checked_at.tzinfo is not None
        assert [str(request.url) for request in sent] == [
            "https://api.openai.com/v1/models"
        ]
        assert sent[0].headers["Authorization"] == f"Bearer {KEY}"

    @pytest.mark.parametrize(
        ("status_code", "error"),
        [
            (401, ConnectionCheckError.AUTHENTICATION_FAILED),
            (403, ConnectionCheckError.AUTHENTICATION_FAILED),
            (404, ConnectionCheckError.NOT_FOUND),
            # Redirects are not followed: the key stays with this host.
            (301, ConnectionCheckError.NOT_FOUND),
            (429, ConnectionCheckError.RATE_LIMITED),
            (400, ConnectionCheckError.REJECTED),
            (500, ConnectionCheckError.PROVIDER_ERROR),
            (503, ConnectionCheckError.PROVIDER_ERROR),
        ],
    )
    async def test_statuses_map_to_a_category(
        self, respond, status_code: int, error: ConnectionCheckError
    ) -> None:
        sent = respond(
            lambda request: httpx.Response(
                status_code, headers={"location": "https://elsewhere.example"}
            )
        )

        check = await probe_connection(_openai(), provider_label="p (openai)")

        assert check.status is ConnectionCheckStatus.FAILED
        assert check.error is error
        assert len(sent) == 1

    async def test_google_refuses_an_invalid_key_with_400(self, respond) -> None:
        respond(lambda request: httpx.Response(400, json={"error": "API_KEY_INVALID"}))
        request = connection_check_request("gemini", KEY, "")
        assert request is not None

        check = await probe_connection(request, provider_label="p (gemini)")

        assert check.error is ConnectionCheckError.AUTHENTICATION_FAILED

    @pytest.mark.parametrize(
        ("raised", "error"),
        [
            (httpx.ReadTimeout("slow"), ConnectionCheckError.TIMEOUT),
            (httpx.ConnectTimeout("slow"), ConnectionCheckError.TIMEOUT),
            (httpx.ConnectError("refused"), ConnectionCheckError.UNREACHABLE),
            (httpx.UnsupportedProtocol("no scheme"), ConnectionCheckError.UNREACHABLE),
        ],
    )
    async def test_network_failures_map_to_a_category(
        self, respond, raised: Exception, error: ConnectionCheckError
    ) -> None:
        def fail(request: httpx.Request) -> httpx.Response:
            raise raised

        respond(fail)

        check = await probe_connection(_openai(), provider_label="p (openai)")

        assert check.status is ConnectionCheckStatus.FAILED
        assert check.error is error

    async def test_a_key_that_is_not_ascii_is_refused_without_a_crash(
        self, respond
    ) -> None:
        respond(lambda request: httpx.Response(200))
        request = connection_check_request("openai", "sk-ä", "")
        assert request is not None

        check = await probe_connection(request, provider_label="p (openai)")

        assert check.error is ConnectionCheckError.AUTHENTICATION_FAILED

    async def test_failures_are_logged_without_key_url_or_body(
        self, respond, caplog: pytest.LogCaptureFixture
    ) -> None:
        respond(
            lambda request: httpx.Response(
                401, json={"error": f"Incorrect API key provided: {KEY}"}
            )
        )

        with caplog.at_level(logging.WARNING):
            # SimpleLogger does not propagate to the root handler caplog uses.
            provider_connection_probe.logger.addHandler(caplog.handler)
            try:
                await probe_connection(_openai(), provider_label="p-1 (openai)")
            finally:
                provider_connection_probe.logger.removeHandler(caplog.handler)

        assert "p-1 (openai)" in caplog.text
        assert "authentication_failed" in caplog.text
        assert "HTTP 401" in caplog.text
        assert KEY not in caplog.text
        assert "api.openai.com" not in caplog.text
