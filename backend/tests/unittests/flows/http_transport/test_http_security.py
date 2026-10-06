from unittest.mock import AsyncMock

import httpx
import pytest
from cryptography.fernet import Fernet

from eneo.flows.http_transport.authored_config import (
    SECRET_SENTINEL,
    CustomHeader,
    HttpAuthApiKey,
    HttpAuthBasicAuth,
    HttpAuthBearer,
    HttpAuthNone,
    HttpAuthoredConfig,
    is_secret_sentinel,
)
from eneo.flows.http_transport.compiler import compile_http_config
from eneo.flows.http_transport.secret_codec import merge_secrets_on_update
from eneo.flows.http_transport.test_action import execute_http_test
from eneo.main.exceptions import (
    EncryptionNotConfiguredException,
    TypedIOValidationException,
)
from eneo.settings.encryption_service import EncryptionService


@pytest.fixture
def encryption_service():
    return EncryptionService(Fernet.generate_key().decode())


def _config(kind, *, stored=False, url="https://example.org/api"):
    secret = "test-only-secret" if stored else SECRET_SENTINEL
    auth = {
        "bearer": HttpAuthBearer(token=secret),
        "api_key": HttpAuthApiKey(header_name="X-Unusual-Credential", key=secret),
        "basic": HttpAuthBasicAuth(username="test-user", password=secret),
        "header": HttpAuthNone(),
    }[kind]
    return HttpAuthoredConfig(
        url=url,
        auth=auth,
        custom_headers=(
            [CustomHeader(name="X-Private", value=secret, secret=True)]
            if kind == "header"
            else []
        ),
    )


@pytest.mark.parametrize("kind", ["bearer", "api_key", "basic", "header"])
@pytest.mark.parametrize(
    "target",
    [
        "http://example.org/api",
        "https://other.example.org/api",
        "https://example.org:8443/api",
        "{{base_url}}/api",
    ],
)
def test_origin_change_cannot_restore_a_saved_credential(kind, target):
    # Mutant: restore stored credentials without proving the destination origin.
    merged = merge_secrets_on_update(
        _config(kind, url=target), _config(kind, stored=True)
    )
    value = (
        merged.custom_headers[0].value
        if kind == "header"
        else getattr(
            merged.auth,
            {"bearer": "token", "api_key": "key", "basic": "password"}[kind],
        )
    )
    assert is_secret_sentinel(value)


@pytest.mark.parametrize("kind", ["bearer", "api_key", "basic", "header"])
def test_same_origin_path_change_keeps_the_saved_credential(kind):
    # Mutant: compare URL strings instead of normalized origins.
    merged = merge_secrets_on_update(
        _config(kind, url="https://EXAMPLE.org:443/other/{{path}}"),
        _config(kind, stored=True),
    )
    assert "test-only-secret" in merged.model_dump_json()


@pytest.mark.parametrize("kind", ["bearer", "api_key", "basic", "header"])
def test_credentials_cannot_be_compiled_for_plaintext_http(kind):
    # Mutant: send a credential over HTTP after URL interpolation.
    with pytest.raises(TypedIOValidationException):
        compile_http_config(
            _config(kind, stored=True, url="http://example.org/api"),
            direction="output",
            method="POST",
        )


@pytest.mark.parametrize(
    "url",
    ["{{base_url}}/api", "https://{{host}}/api", "https://example.org:{{port}}/api"],
)
def test_run_variables_cannot_choose_a_credential_destination(url):
    # Mutant: let a run input redirect a stored credential to another HTTPS origin.
    with pytest.raises(TypedIOValidationException):
        compile_http_config(
            _config("bearer", stored=True, url=url),
            direction="output",
            method="POST",
            interpolate=lambda template, _context: "https://other.example.org/api",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["bearer", "api_key", "basic", "header"])
async def test_http_test_preview_does_not_reveal_a_credential(kind, encryption_service):
    # Mutant: mask by header-name list or reveal a credential prefix.
    send = AsyncMock(return_value=httpx.Response(200, text="ok"))
    result = await execute_http_test(
        config=_config(kind, stored=True),
        direction="output",
        method="POST",
        interpolate=lambda template, _context: template,
        send_http_request=send,
        encryption_service=encryption_service,
        max_timeout=120,
    )
    assert result.success
    assert result.request_preview is not None
    headers = result.request_preview.headers
    assert all(value == "[REDACTED]" for value in headers.values())


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["interpolation", "network"])
async def test_http_test_does_not_publish_raw_exception_details(
    failure, encryption_service
):
    # Mutant: return the interpolation/HTTP exception text to the browser.
    from eneo.flows.http_transport.errors import HttpTemplateInterpolationError

    private = "test-only-secret/internal-system-detail"

    def interpolate(template, _context):
        if failure == "interpolation":
            raise HttpTemplateInterpolationError(private)
        return template

    send = AsyncMock(side_effect=httpx.ConnectError(private))
    result = await execute_http_test(
        config=_config("header", stored=True),
        direction="output",
        method="POST",
        interpolate=interpolate,
        send_http_request=send,
        encryption_service=encryption_service,
        max_timeout=120,
    )
    assert not result.success
    assert private not in (result.error_message or "")


@pytest.mark.asyncio
@pytest.mark.parametrize("key_state", ["missing", "wrong", "correct"])
async def test_a_saved_credential_is_sent_only_when_the_key_authenticates_it(key_state):
    # Mutant: send stored ciphertext or decrypt without a valid active key.
    from cryptography.fernet import Fernet

    from eneo.settings.encryption_service import EncryptionService

    encryption = EncryptionService(Fernet.generate_key().decode())
    stored = _config("bearer", stored=True)
    stored.auth.token = encryption.encrypt("test-only-secret")
    key = (
        encryption
        if key_state == "correct"
        else EncryptionService(Fernet.generate_key().decode())
        if key_state == "wrong"
        else None
    )
    send = AsyncMock(return_value=httpx.Response(200, text="ok"))
    result = await execute_http_test(
        config=_config("bearer"),
        stored_config=stored,
        encryption_service=key,
        direction="output",
        method="POST",
        interpolate=lambda template, _context: template,
        send_http_request=send,
        max_timeout=120,
    )
    assert result.success == (key_state == "correct")
    if key_state == "correct":
        assert (
            send.await_args.kwargs["headers"]["Authorization"]
            == "Bearer test-only-secret"
        )
    else:
        send.assert_not_awaited()
        assert result.error_code.value == "HTTP_UNRESOLVED_STORED_SECRET"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["bearer", "api_key", "basic", "header"])
async def test_known_credentials_echoed_by_the_target_are_not_previewed(
    kind, encryption_service
):
    # Mutant: return an authenticated endpoint's echo unchanged.
    config = _config(kind, stored=True)
    compiled = compile_http_config(config, direction="output", method="POST")
    echo = " | ".join(compiled.headers.values()) + " test-only-secret"
    result = await execute_http_test(
        config=config,
        direction="output",
        method="POST",
        interpolate=lambda template, _context: template,
        send_http_request=AsyncMock(return_value=httpx.Response(200, text=echo)),
        encryption_service=encryption_service,
        max_timeout=120,
    )
    assert result.success
    assert result.response_preview is None


@pytest.mark.asyncio
async def test_an_authenticated_response_cannot_echo_an_encoded_credential(
    encryption_service,
):
    # Mutant: try to sanitize arbitrary response encodings by literal replacement.
    config = HttpAuthoredConfig(
        url="https://example.org/api", auth=HttpAuthBearer(token='test-only"credential')
    )
    result = await execute_http_test(
        config=config,
        direction="output",
        method="POST",
        encryption_service=encryption_service,
        interpolate=lambda template, _context: template,
        send_http_request=AsyncMock(
            return_value=httpx.Response(200, json={"echo": 'test-only"credential'})
        ),
        max_timeout=120,
    )
    assert result.success
    assert result.response_preview is None


@pytest.mark.asyncio
async def test_new_credentials_cannot_be_tested_without_active_encryption():
    # Mutant: bypass the save owner's encryption requirement in HTTP testing.
    send = AsyncMock(return_value=httpx.Response(200))
    with pytest.raises(EncryptionNotConfiguredException):
        await execute_http_test(
            config=_config("bearer", stored=True),
            encryption_service=EncryptionService(),
            direction="output",
            method="POST",
            interpolate=lambda template, _context: template,
            send_http_request=send,
            max_timeout=120,
        )
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_new_encryption_prefix_literal_is_sent_as_authored(encryption_service):
    # Mutant: mistake an authored encryption-prefix literal for stored ciphertext.
    literal = "enc:fernet:v1:test-only-literal"
    config = HttpAuthoredConfig(
        url="https://example.org", auth=HttpAuthBearer(token=literal)
    )
    send = AsyncMock(return_value=httpx.Response(200))
    result = await execute_http_test(
        config=config,
        encryption_service=encryption_service,
        direction="output",
        method="POST",
        interpolate=lambda template, _context: template,
        send_http_request=send,
        max_timeout=120,
    )
    assert result.success
    assert send.await_args.kwargs["headers"]["Authorization"] == f"Bearer {literal}"


@pytest.mark.parametrize(
    "url,credential", [("http://example.org", False), ("https://example.org", True)]
)
def test_https_credentials_and_anonymous_http_remain_available(url, credential):
    # Mutant: deny all HTTP requests or disable authentication altogether.
    config = (
        _config("bearer", stored=True, url=url)
        if credential
        else HttpAuthoredConfig(url=url)
    )
    assert compile_http_config(config, direction="output", method="POST").url == url
