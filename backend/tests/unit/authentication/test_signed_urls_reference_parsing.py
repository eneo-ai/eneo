"""Unit tests for signed attachment-reference URL parsing.

``parse_file_reference_url`` is the inverse of
``build_signed_original_download_url`` and is host-agnostic on purpose: the
HMAC token is the sole authorizer, so links minted against either the public
origin or the tool-facing reference base URL both resolve.
"""

from uuid import uuid4

from eneo.authentication.signed_urls import (
    build_signed_original_download_url,
    looks_like_reference_url,
    parse_file_reference_url,
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
