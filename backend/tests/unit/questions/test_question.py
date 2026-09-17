"""ToolCallInfo never carries a live signed download token.

The record is what gets persisted on the question, streamed to the chat UI,
returned by the tool-result endpoint and replayed to the model. The tool
already consumed the link, and later turns get fresh reference entries, so
the token is stripped on construction and on load alike.
"""

from uuid import uuid4

from eneo.authentication.signed_urls import (
    REDACTED_TOKEN,
    build_signed_original_download_url,
)
from eneo.questions.question import ToolCallInfo


def _url():
    return build_signed_original_download_url(
        file_id=uuid4(),
        base_url="http://host.docker.internal:8123",
        expires_in=3600,
        tenant_id=uuid4(),
    )


def test_arguments_and_result_are_redacted_on_construction():
    url = _url()
    token = url.split("token=")[1]

    info = ToolCallInfo(
        server_name="Analys",
        tool_name="read_urls",
        arguments={"urls": [url], "offset": 0},
        result='{"files":[{"url":"' + url + '"}]}',
    )

    assert info.arguments == {
        "urls": [url.replace(token, REDACTED_TOKEN)],
        "offset": 0,
    }
    assert info.result is not None
    assert token not in info.result
    assert REDACTED_TOKEN in info.result


def test_rows_persisted_with_a_token_are_redacted_on_load():
    url = _url()
    token = url.split("token=")[1]

    info = ToolCallInfo.model_validate(
        {
            "server_name": "files",
            "tool_name": "read_file",
            "arguments": {"url": url},
            "result": f"File: a.pdf\n\n{url}",
        }
    )

    assert token not in str(info.arguments)
    assert token not in (info.result or "")


def test_values_without_links_are_untouched():
    info = ToolCallInfo(
        server_name="web",
        tool_name="search",
        arguments={"query": "token=abc in prose", "limit": 3},
        result="plain text",
    )

    assert info.arguments == {"query": "token=abc in prose", "limit": 3}
    assert info.result == "plain text"
