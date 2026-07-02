from __future__ import annotations

from eneo.flows.domain.flow import clone_json_object


def test_clone_json_object_returns_none_for_non_mapping() -> None:
    assert clone_json_object(None) is None
    assert clone_json_object(["not", "an", "object"]) is None


def test_clone_json_object_returns_empty_dict_for_empty_mapping() -> None:
    cloned = clone_json_object({})

    assert cloned == {}
    assert cloned is not None


def test_clone_json_object_copies_string_keyed_mapping_entries() -> None:
    nested = ["audio/mpeg"]
    source = {
        "enabled": True,
        "accepted_mimetypes_override": nested,
        1: "not-json",
    }

    cloned = clone_json_object(source)

    assert cloned == {
        "enabled": True,
        "accepted_mimetypes_override": nested,
    }
    assert cloned is not source
    assert cloned["accepted_mimetypes_override"] is nested
