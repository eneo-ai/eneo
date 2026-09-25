"""Unit tests for signed attachment-reference URL parsing.

``parse_file_reference_url`` is the inverse of
``build_signed_original_download_url`` and is host-agnostic on purpose: the
HMAC token is the sole authorizer, so links minted against either the public
origin or the tool-facing reference base URL both resolve.
"""

from uuid import uuid4

from eneo.authentication.signed_urls import (
    REDACTED_TOKEN,
    build_signed_original_download_url,
    looks_like_reference_url,
    parse_file_reference_url,
    redact_reference_tokens,
)


def _signed_url(file_id, base_url="https://eneo.example"):
    return build_signed_original_download_url(
        file_id=file_id,
        base_url=base_url,
        expires_in=3600,
        tenant_id=uuid4(),
    )


class TestParseFileReferenceUrl:
    def test_extracts_file_id_and_token_from_signed_url(self):
        file_id = uuid4()
        url = _signed_url(file_id)

        parsed = parse_file_reference_url(url)

        assert parsed is not None
        parsed_id, token = parsed
        assert parsed_id == file_id
        assert token == url.split("token=")[1]

    def test_host_is_irrelevant(self):
        # The signed token authorizes, not the host, so links minted against
        # the public origin and the tool-facing base URL both resolve.
        file_id = uuid4()
        url = _signed_url(file_id, base_url="http://internal:8123")

        parsed = parse_file_reference_url(url)
        assert parsed is not None
        assert parsed[0] == file_id

    def test_accepts_path_without_trailing_slash(self):
        file_id = uuid4()
        url = f"https://eneo.example/api/v1/files/{file_id}/original/download?token=tok"

        parsed = parse_file_reference_url(url)
        assert parsed == (file_id, "tok")

    def test_rejects_url_without_token(self):
        file_id = uuid4()
        assert (
            parse_file_reference_url(
                f"https://eneo.example/api/v1/files/{file_id}/original/download/"
            )
            is None
        )

    def test_rejects_non_download_urls(self):
        assert parse_file_reference_url("https://example.com/some/other/path") is None
        assert parse_file_reference_url("not a url at all") is None


class TestLooksLikeReferenceUrl:
    def test_accepts_minted_urls_on_any_host(self):
        assert looks_like_reference_url(_signed_url(uuid4()))
        assert looks_like_reference_url(
            _signed_url(uuid4(), base_url="http://host.docker.internal:8123")
        )

    def test_rejects_non_reference_urls(self):
        assert not looks_like_reference_url("https://example.com/report.pdf")
        assert not looks_like_reference_url("not a url at all")
        assert not looks_like_reference_url("")


class TestRedactReferenceTokens:
    """The signed token is a bearer credential; once a tool has used a link
    the token must not survive in anything persisted or displayed."""

    def test_token_is_replaced_but_the_link_stays_recognizable(self):
        file_id = uuid4()
        url = _signed_url(file_id)

        redacted = redact_reference_tokens(url)

        assert isinstance(redacted, str)
        assert redacted.endswith(f"token={REDACTED_TOKEN}")
        assert url.split("token=")[1] not in redacted
        assert redacted.startswith(f"https://eneo.example/api/v1/files/{file_id}/")
        assert looks_like_reference_url(redacted)

    def test_walks_nested_arguments_and_leaves_other_values_alone(self):
        url = _signed_url(uuid4())
        arguments = {
            "urls": [url, "https://example.org/page?token=keep-me"],
            "offset": 0,
            "nested": {"note": f"see {url} and {url}"},
        }

        redacted = redact_reference_tokens(arguments)

        assert isinstance(redacted, dict)
        assert redacted["offset"] == 0
        assert redacted["urls"][1] == "https://example.org/page?token=keep-me"
        assert redacted["urls"][0].endswith(f"token={REDACTED_TOKEN}")
        assert redacted["nested"]["note"].count(REDACTED_TOKEN) == 2
        assert "token=ey" not in redacted["nested"]["note"]

    def test_result_text_embedding_the_link_is_redacted(self):
        url = _signed_url(uuid4())
        result = '{"files":[{"url":"' + url + '","status":"ready"}]}'

        redacted = redact_reference_tokens(result)

        assert isinstance(redacted, str)
        assert url.split("token=")[1] not in redacted
        assert f'token={REDACTED_TOKEN}","status":"ready"' in redacted

    def test_non_string_values_pass_through(self):
        assert redact_reference_tokens(None) is None
        assert redact_reference_tokens(7) == 7
