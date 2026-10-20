"""What a revision changed against the one before it, and where each step of
the draft comes from (pure comparisons over the revision rows)."""

from datetime import datetime, timezone
from uuid import uuid4

from eneo.database.tables.flow_tables import FlowRevisions
from eneo.flows.flow_assembler import revision_changes, step_origins


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


# --- Step origins ---


AUTHOR = uuid4()


def _revision(number: int, channel: str, *steps: dict) -> FlowRevisions:
    return FlowRevisions(
        revision=number,
        channel=channel,
        name="Brief",
        definition=_definition(*steps),
        created_at=datetime(2026, 10, 20, 12, number, tzinfo=timezone.utc),
        principal_user_id=AUTHOR,
    )


def _origins_by_key(current: dict, revisions: list[FlowRevisions]) -> dict:
    return {origin.key: origin for origin in step_origins(current, revisions)}


def test_a_flow_with_one_revision_originates_every_step_there():
    first = _revision(1, "mcp", _llm("draft"), _llm("wrap"))

    origins = step_origins(first.definition, [first])

    assert [(o.key, o.revision, o.channel) for o in origins] == [
        ("draft", 1, "mcp"),
        ("wrap", 1, "mcp"),
    ]
    assert origins[0].changed_at == first.created_at
    assert origins[0].changed_by_user_id == AUTHOR
    assert origins[0].assistant_revision is None


def test_a_step_changed_by_the_panel_points_back_at_the_chats_version():
    chat = _revision(1, "mcp", _llm("draft"), _llm("wrap"))
    panel = _revision(2, "api", _llm("draft", prompt="longer"), _llm("wrap"))

    origins = _origins_by_key(panel.definition, [panel, chat])

    assert (origins["draft"].revision, origins["draft"].channel) == (2, "api")
    assert origins["draft"].assistant_revision == 1
    # The untouched step keeps the chat's save as its origin, with no
    # earlier chat version to go back to.
    assert (origins["wrap"].revision, origins["wrap"].channel) == (1, "mcp")
    assert origins["wrap"].assistant_revision is None


def test_the_origin_is_the_oldest_revision_of_the_unbroken_run_of_equal_bodies():
    # draft: A (rev 1), B (rev 2), A again (rev 3): the origin is rev 3, not 1.
    one = _revision(1, "mcp", _llm("draft"))
    two = _revision(2, "mcp", _llm("draft", prompt="B"))
    three = _revision(3, "api", _llm("draft"))
    four = _revision(4, "api", _llm("draft"), _llm("new"))

    origins = _origins_by_key(four.definition, [four, three, two, one])

    assert origins["draft"].revision == 3
    assert origins["draft"].assistant_revision == 2
    assert origins["new"].revision == 4


def test_server_assigned_ids_do_not_break_the_run_and_unknown_steps_have_none():
    old = _revision(1, "mcp", {**_llm("draft"), "id": "a"})
    current = _definition({**_llm("draft"), "id": "b"}, _llm("fresh"))

    origins = _origins_by_key(current, [old])

    assert origins["draft"].revision == 1
    assert "fresh" not in origins


def test_no_history_means_no_origins():
    assert step_origins(_definition(_llm("draft")), []) == []
