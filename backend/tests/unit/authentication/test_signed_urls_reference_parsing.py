"""Unit tests for signed attachment-reference URL parsing.

``parse_file_reference_url`` is the inverse of
``build_signed_original_download_url`` and is host-agnostic on purpose: the
HMAC token is the sole authorizer, so links minted against either the public
origin or the tool-facing reference base URL both resolve.
"""

import json
from uuid import uuid4

import pytest

from eneo.authentication.signed_urls import (
    REDACTED_TOKEN,
    build_signed_original_download_url,
    looks_like_reference_url,
    parse_file_reference_url,
    redact_reference_tokens,
    reference_file_ids,
    restore_reference_tokens,
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


class TestReferenceFileIds:
    """Every signed link in a tool call's arguments is found, wherever it sits,
    so the proxy can tell which files the call would hand to a tool."""

    def test_finds_links_nested_in_objects_lists_and_text(self):
        first, second, third = uuid4(), uuid4(), uuid4()
        arguments = {
            "file": {"url": _signed_url(first), "filename": "a.xlsx"},
            "files": [{"url": _signed_url(second), "alias": "b"}],
            "content": f"See {_signed_url(third)} for the figures.",
            "limit": 10,
        }

        assert reference_file_ids(arguments) == {first, second, third}

    def test_percent_encoded_link_names_the_same_file(self):
        file_id = uuid4()
        encoded = _signed_url(file_id).replace("/original/", "/origina%6C/")

        assert reference_file_ids(encoded) == {file_id}

    def test_redacted_links_are_skipped_unless_asked_for(self):
        file_id = uuid4()
        redacted = redact_reference_tokens(_signed_url(file_id))

        assert reference_file_ids(redacted) == set()
        assert reference_file_ids(redacted, include_redacted=True) == {file_id}

    def test_other_links_and_values_yield_nothing(self):
        assert reference_file_ids("https://example.org/page?token=keep-me") == set()
        assert reference_file_ids({"n": 7, "none": None, "items": []}) == set()


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


class TestRestoreReferenceTokens:
    """Replay swaps redacted links for this request's fresh ones, so a model
    copying the URL from its own earlier call sends a working link."""

    def test_redacted_links_get_the_fresh_url_for_their_file(self):
        file_id, other_id = uuid4(), uuid4()
        stored = redact_reference_tokens(
            {
                "file": {"url": _signed_url(file_id), "filename": "a.xlsx"},
                "files": [{"url": _signed_url(other_id), "alias": "b"}],
                "sql": "SELECT 1",
            }
        )
        fresh = _signed_url(file_id, base_url="http://backend:8000")

        replayed = restore_reference_tokens(stored, {file_id: fresh})

        assert isinstance(replayed, dict)
        assert replayed["file"]["url"] == fresh
        # No fresh URL for this file: it stays redacted rather than guessed.
        assert replayed["files"][0]["url"].endswith(f"token={REDACTED_TOKEN}")
        assert replayed["sql"] == "SELECT 1"

    def test_live_links_and_other_values_are_left_alone(self):
        live = _signed_url(uuid4())
        assert restore_reference_tokens(live, {uuid4(): "x"}) == live
        assert restore_reference_tokens(None, {}) is None


class TestCurrentReferences:
    def test_nested_inputs_use_current_link_without_mutating_arguments(self):
        from eneo.authentication.signed_urls import use_current_file_references

        file_id = uuid4()
        current = _signed_url(file_id)
        for token in ("old-token", "REDACTED", "incorrect-token"):
            old = current.split("?token=")[0] + "?token=" + token
            args = {"file": {"url": old}, "images": [{"url": old}]}
            result = use_current_file_references(args, {file_id: current})
            assert result["file"]["url"] == current
            assert result["images"][0]["url"] == current
            assert args["file"]["url"] == old

    def test_no_credentials_for_foreign_origins_paths_or_files(self):
        from eneo.authentication.signed_urls import use_current_file_references

        file_id = uuid4()
        current = _signed_url(file_id)
        for url in (
            current.replace("eneo.example", "foreign.example"),
            current.replace("https://", "http://"),
            current.replace("eneo.example", "eneo.example@foreign.example"),
            current.replace("/api/v1/", "/different/api/v1/"),
            current + "#fragment",
            _signed_url(uuid4()),
        ):
            assert use_current_file_references(url, {file_id: current}) == url
        assert use_current_file_references(current, {}) == current


@pytest.mark.parametrize(
    "suffix",
    ["", "?token=", "LITERALLY?token=model-token", "extra-word/?token=model-token"],
)
def test_known_reference_is_resolved_without_relying_on_model_token_or_suffix(suffix):
    from eneo.authentication.signed_urls import use_current_file_references

    file_id = uuid4()
    current = _signed_url(file_id)
    supplied = current.split("?")[0] + suffix
    assert use_current_file_references(supplied, {file_id: current}) == current
    assert use_current_file_references(supplied, {}) == supplied


@pytest.mark.parametrize("suffix", ["", "?token=", "LITERALLY?token=model-token"])
def test_conversation_admission_identifies_tokenless_and_malformed_links(suffix):
    file_id = uuid4()
    supplied = _signed_url(file_id).split("?")[0] + suffix
    assert reference_file_ids({"source": {"url": supplied}}, include_redacted=True) == {
        file_id
    }


def test_reference_repair_does_not_guess_origins_paths_ids_or_embedded_prose():
    from eneo.authentication.signed_urls import use_current_file_references

    file_id = uuid4()
    current = _signed_url(file_id)
    path = current.split("?")[0]
    for supplied in (
        path.replace("eneo.example", "foreign.example"),
        path.replace("https://", "http://"),
        path.replace("eneo.example", "eneo.example@foreign.example"),
        path.replace("/api/v1/", "/different/api/v1/"),
        path.replace("/original/", "/processing/"),
        path + "../other?token=bad",
        path + "%2e%2e?token=bad",
        path + "extra/nested?token=bad",
        path + "#fragment",
        path + "?token=bad extra prose",
        path + "?token=bad\n",
        "See " + path,
        _signed_url(uuid4()).split("?")[0],
    ):
        assert use_current_file_references(supplied, {file_id: current}) == supplied


@pytest.mark.parametrize("tail", ["", "LITERALLY", "other/path", "LITERALLY/"])
def test_tokens_are_masked_even_when_the_original_download_path_is_malformed(tail):
    from eneo.authentication.signed_urls import redact_reference_tokens_in_json

    # A synthetic token: never print a real credential in test output.
    url = f"https://eneo.example/api/v1/files/{uuid4()}/original/download/{tail}?token=synthetic.credential="
    nested = {"sheets": [{"source": {"url": url}}]}
    masked = redact_reference_tokens(nested)
    assert masked["sheets"][0]["source"]["url"].endswith("token=REDACTED")
    for raw in (json.dumps(nested), json.dumps(nested).replace("/", r"\/")):
        assert "synthetic" not in redact_reference_tokens_in_json(raw)
        # Streaming fragments must not disclose the token before JSON is complete.
        token_start = raw.index("synthetic")
        for length in range(
            token_start + 1, token_start + len("synthetic.credential=") + 1
        ):
            redacted = redact_reference_tokens_in_json(raw[:length])
            assert redacted == raw[:token_start] + "REDACTED"
