from copy import deepcopy
from uuid import UUID, uuid4

import jsonschema
import pytest

from eneo.files.model_file_references import (
    UnknownFileReference,
    file_handle,
    handle_file_ids,
    model_file_references,
    model_file_schema,
    resolve_file_handles,
)


def link(file_id, token="test-secret"):
    return (
        f"https://eneo.example/api/v1/files/{file_id}/original/download/?token={token}"
    )


def test_handles_are_stable_and_do_not_encode_credentials():
    file_id = UUID("12345678-1234-1234-1234-123456789abc")
    handle = file_handle(file_id)
    assert handle == "eneo-file:12345678123412341234123456789abc"
    assert handle_file_ids({"source": {"url": handle}}) == {file_id}
    assert resolve_file_handles(handle, {file_id: link(file_id, "first")}) == link(
        file_id, "first"
    )
    assert resolve_file_handles(handle, {file_id: link(file_id, "next")}) == link(
        file_id, "next"
    )


@pytest.mark.parametrize(
    "handle",
    [file_handle(uuid4()), "eneo-file:invented", "eneo-file:", "eneo-file:" + "a" * 33],
)
def test_unknown_malformed_and_unavailable_handles_fail_closed(handle):
    with pytest.raises(UnknownFileReference):
        resolve_file_handles({"images": [{"url": handle}]}, {})


def test_nested_references_resolve_without_changing_stored_arguments_or_text():
    file_id = uuid4()
    handle = file_handle(file_id)
    args = {
        "revises": {"url": handle},
        "sheets": [{"source": {"url": handle}}],
        "content": "Discuss " + handle,
        "url": "https://external.example/data.csv",
    }
    original = deepcopy(args)
    result = resolve_file_handles(args, {file_id: link(file_id)})
    assert args == original
    assert result["revises"]["url"] == link(file_id)
    assert result["sheets"][0]["source"]["url"] == link(file_id)
    assert result["content"] == original["content"]
    assert result["url"] == original["url"]


def test_tool_echo_and_legacy_history_never_restore_credentials_to_model():
    file_id, foreign = uuid4(), uuid4()
    current = link(file_id)
    original = {
        "text": '{"url":"' + current + '"}',
        "escaped": current.replace("/", r"\/"),
        "history": link(file_id, "REDACTED"),
        "foreign": link(foreign),
    }
    result = model_file_references(original, {file_id: current})
    assert "test-secret" not in str(result)
    assert result["text"] == '{"url":"' + file_handle(file_id) + '"}'
    assert result["escaped"] == file_handle(file_id)
    assert result["history"] == file_handle(file_id)
    assert result["foreign"].endswith("token=REDACTED")
    assert original["history"].startswith("https://")


def test_model_schema_accepts_handles_and_normal_urls_without_changing_provider_contract():
    provider = {
        "type": "object",
        "required": ["sheets"],
        "properties": {
            "sheets": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "source": {
                            "type": "object",
                            "properties": {
                                "url": {"type": "string", "pattern": "^https://"}
                            },
                        },
                        "name": {"type": "string", "maxLength": 20},
                    },
                },
            },
        },
    }
    original = deepcopy(provider)
    model = model_file_schema(provider)
    fid = uuid4()
    args = {"sheets": [{"source": {"url": file_handle(fid)}, "name": "Summary"}]}
    jsonschema.validate(args, model)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(args, provider)
    jsonschema.validate(resolve_file_handles(args, {fid: link(fid)}), provider)
    assert provider == original
    assert model["properties"]["sheets"]["items"]["properties"]["name"] == {
        "type": "string",
        "maxLength": 20,
    }
