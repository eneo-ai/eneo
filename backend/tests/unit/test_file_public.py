from uuid import uuid4

from eneo.files.file_models import FilePublic


def _file_public(**overrides):
    values = {
        "id": uuid4(),
        "name": "policy.pdf",
        "mimetype": "application/pdf",
        "size": 123,
    }
    values.update(overrides)
    return FilePublic(**values)


def test_download_capability_is_an_explicit_projection():
    public = _file_public(has_download_reference=True)

    assert public.model_dump()["has_download_reference"] is True


def test_download_capability_defaults_to_false():
    assert _file_public().has_download_reference is False


def test_storage_internals_never_reach_the_payload():
    public = _file_public(has_download_reference=True)

    payload = public.model_dump()

    assert "storage_key" not in payload
    assert not any("object" in key for key in payload)
