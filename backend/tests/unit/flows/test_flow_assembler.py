"""What a revision changed against the one before it (pure comparison)."""

from eneo.flows.flow_assembler import revision_changes


def _definition(*steps: dict, form_fields: list[dict] | None = None) -> dict:
    return {
        "schema_version": 1,
        "form_fields": form_fields or [],
        "steps": list(steps),
    }


def _llm(key: str, name: str | None = None, **extra) -> dict:
    return {
        "kind": "llm",
        "key": key,
        "id": f"id-{key}",
        "name": name or key.title(),
        "prompt": "p",
        **extra,
    }


TOPIC = {"key": "topic", "label": "Topic", "type": "text", "required": True}


def test_first_revision_is_initial_with_nothing_else():
    changes = revision_changes("Brief", None, _definition(_llm("draft")), None)

    assert changes.is_initial is True
    assert changes.name_changed is False
    assert changes.description_changed is False
    assert changes.form_fields_changed is False
    assert changes.steps_added == []
    assert changes.steps_removed == []
    assert changes.steps_changed == []


def test_steps_match_by_key_and_name_the_step_of_their_own_revision():
    previous = _definition(_llm("draft"), _llm("old", "Old step"), _llm("same"))
    current = _definition(
        _llm("draft", "Draft", prompt="longer"),
        _llm("same"),
        _llm("new", "New step"),
    )

    changes = revision_changes("Brief", None, current, ("Brief", None, previous))

    assert changes.is_initial is False
    assert changes.steps_added == ["New step"]
    assert changes.steps_removed == ["Old step"]
    assert changes.steps_changed == ["Draft"]


def test_server_assigned_ids_never_count_as_a_change():
    previous = _definition({**_llm("draft"), "id": "a"})
    current = _definition({**_llm("draft"), "id": "b"})

    changes = revision_changes("Brief", None, current, ("Brief", None, previous))

    assert changes.steps_changed == []


def test_name_description_and_form_fields_are_compared_separately():
    previous = _definition(_llm("draft"), form_fields=[TOPIC])
    current = _definition(_llm("draft"), form_fields=[{**TOPIC, "required": False}])

    changes = revision_changes(
        "Weekly brief", "Writes it", current, ("Brief", None, previous)
    )

    assert changes.name_changed is True
    assert changes.description_changed is True
    assert changes.form_fields_changed is True
    assert changes.steps_changed == []


def test_an_empty_description_equals_a_missing_one():
    definition = _definition(_llm("draft"))

    changes = revision_changes("Brief", "", definition, ("Brief", None, definition))

    assert changes.description_changed is False
