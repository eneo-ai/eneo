from eneo.files.file_models import AcceptedFileType


def test_for_mimetype_derives_extensions():
    accepted = AcceptedFileType.for_mimetype("application/pdf", size_limit=1)

    assert accepted.model_dump() == {
        "mimetype": "application/pdf",
        "size_limit": 1,
        "extensions": [".pdf"],
    }


def test_for_mimetype_lists_every_known_extension():
    accepted = AcceptedFileType.for_mimetype("text/plain", size_limit=1)

    assert accepted.extensions == [".txt", ".text"]


def test_for_mimetype_has_no_extensions_for_unknown_mimetype():
    accepted = AcceptedFileType.for_mimetype("application/x-unknown", size_limit=1)

    assert accepted.extensions == []


def test_extensions_is_part_of_the_api_contract():
    assert "extensions" in AcceptedFileType.model_json_schema()["required"]
