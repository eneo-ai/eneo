from types import SimpleNamespace

from eneo.completion_models.infrastructure.provider_response_ids import (
    extract_provider_response_id,
)


def test_extract_provider_response_id_reads_string_ids_from_objects_and_mappings() -> (
    None
):
    assert (
        extract_provider_response_id(SimpleNamespace(id="resp-object")) == "resp-object"
    )
    assert extract_provider_response_id({"id": "resp-mapping"}) == "resp-mapping"
    assert extract_provider_response_id(SimpleNamespace(id="  ")) is None
    assert extract_provider_response_id({"id": None}) is None
