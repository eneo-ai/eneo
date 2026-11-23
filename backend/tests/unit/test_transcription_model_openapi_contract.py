"""The tenant transcription-model writes document the 400 they can answer.

Turning live text on for a model whose provider cannot carry it answers 400
with what to change, on create and on update alike."""

import pytest

from eneo.server.main import get_application

PATH = "/api/v1/admin/tenant-models/transcription/"


@pytest.fixture(scope="module")
def paths() -> dict:
    return get_application().openapi()["paths"]


@pytest.mark.parametrize(
    ("path", "method"), [(PATH, "post"), (f"{PATH}{{model_id}}/", "put")]
)
def test_turning_live_text_on_documents_its_refusal(
    paths: dict, path: str, method: str
):
    assert "400" in paths[path][method]["responses"]
