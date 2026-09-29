import pytest

from eneo.flows.ai_builder.ai_builder_primary_input_fields import (
    MAIN_TEXT_FIELD_NAMES,
    declared_main_text_field,
    dropped_primary_field_names,
    elect_main_text_field,
    free_main_text_name,
    is_main_text_field,
    is_primary_runtime_input_shadow_field,
    main_text_beside_fields_detail,
    main_text_has_no_place,
    main_text_is_a_field,
    main_text_name_collision,
    primary_input_shadow_alias_input_types,
    split_primary_runtime_input_shadow_names,
)
from eneo.flows.flow_authoring_spec import (
    InputType,
)


def test_primary_input_shadow_aliases_cover_all_concrete_input_types() -> None:
    expected = {
        input_type for input_type in InputType if input_type is not InputType.ANY
    }

    assert primary_input_shadow_alias_input_types() == expected


def test_audio_transcript_names_shadow_primary_audio_input() -> None:
    for variable_name in (
        "transcript",
        "transcription",
        "transcribed_text",
        "transkribering",
        "transkription",
    ):
        assert is_primary_runtime_input_shadow_field(
            variable_name=variable_name,
            field_type="text",
            runtime_input_type=InputType.AUDIO,
        )


TEXT = InputType.TEXT


@pytest.mark.parametrize(
    ("input_type", "fields", "is_field", "no_place"),
    [
        # The run dialog's text box is the main text's place: nothing to decide.
        (TEXT, [], False, False),
        (TEXT, [("input", "text")], False, False),
        (TEXT, [("input", "text"), ("indata_text", "text")], False, False),
        # Other fields take the text box away: a field named like the main
        # input is the main text, and without one the main text has no place.
        (TEXT, [("tone", "text"), ("input", "text")], True, False),
        (TEXT, [("tone", "text"), ("indata_text", "text")], True, False),
        (TEXT, [("tone", "text")], True, True),
        (TEXT, [("input", "select"), ("tone", "text")], True, True),
        # Only a text flow has a main text to place.
        (InputType.DOCUMENT, [("tone", "text")], False, False),
        (InputType.AUDIO, [("tone", "text")], False, False),
        (None, [("tone", "text")], False, False),
    ],
)
def test_the_main_text_of_a_text_flow_is_a_field_beside_other_fields(
    input_type: InputType | None,
    fields: list[tuple[str, str]],
    is_field: bool,
    no_place: bool,
) -> None:
    assert (
        main_text_is_a_field(runtime_input_type=input_type, fields=fields) is is_field
    )
    assert (
        main_text_has_no_place(runtime_input_type=input_type, fields=fields) is no_place
    )


def test_a_read_of_a_kept_declared_name_survives_but_an_undeclared_shadow_does_not() -> (
    None
):
    kept, dropped = split_primary_runtime_input_shadow_names(
        field_names=["tone", "input", "indata_text", "text"],
        runtime_input_type=TEXT,
        kept_names=frozenset({"input", "indata_text"}),
    )
    assert kept == ["tone", "input", "indata_text"]
    assert dropped == ["text"]

    # Nothing declared: every primary-looking read is still the shadow it was.
    kept, dropped = split_primary_runtime_input_shadow_names(
        field_names=["tone", "input"], runtime_input_type=TEXT
    )
    assert (kept, dropped) == (["tone"], ["input"])


def test_the_refusal_names_only_the_repairs_the_caller_can_make() -> None:
    tone = [("tone", "text")]
    edit = main_text_beside_fields_detail(can_declare_fields=True, fields=tone)
    create = main_text_beside_fields_detail(can_declare_fields=False, fields=tone)
    taken = main_text_beside_fields_detail(
        can_declare_fields=True,
        fields=[("input", "select"), ("indata_text", "select")],
    )
    elected = main_text_beside_fields_detail(
        can_declare_fields=True, fields=[("indata_text", "text"), ("tone", "text")]
    )

    assert "declare the main text as a required text form field named `input`" in edit
    assert "uses_form_fields" in edit
    assert "declare the main text" not in create
    assert "ask the person" in edit.lower() and "ask the person" in create.lower()
    # Every name taken: it does not offer a name that would collide.
    assert "declare the main text" not in taken
    assert "`input`, `indata_text`" in taken and "rename that field" in taken
    # A main-text field exists: the step reads it, nothing new is declared.
    assert "The main text is the form field `indata_text`" in elected
    assert "declare the main text" not in elected


@pytest.mark.parametrize(
    ("ui_language", "label"),
    [
        ("sv", "Text att bearbeta"),
        ("sv-SE", "Text att bearbeta"),
        ("en", "Text to process"),
        ("EN-gb", "Text to process"),
        (None, "Text att bearbeta"),
    ],
)
def test_the_declared_main_text_field_is_required_text_with_a_label_in_the_ui_language(
    ui_language: str | None, label: str
) -> None:
    field = declared_main_text_field(name="input", ui_language=ui_language)

    assert (field.name, field.type, field.required, field.label) == (
        MAIN_TEXT_FIELD_NAMES[0],
        "text",
        True,
        label,
    )
    # It is the name main_text_is_a_field recognises, so a later pass keeps it.
    assert main_text_is_a_field(
        runtime_input_type=TEXT,
        fields=[("tone", "text"), (field.name, field.type)],
    )
    assert not main_text_has_no_place(
        runtime_input_type=TEXT, fields=[("tone", "text"), (field.name, field.type)]
    )


def test_the_main_text_names_are_the_primary_input_names_the_form_schema_allows() -> (
    None
):
    # `text` is a primary-input name but a reserved payload key: the form-schema
    # contract rejects it as a field name, so it can never carry the main text.
    assert MAIN_TEXT_FIELD_NAMES == ("input", "indata_text")
    assert is_primary_runtime_input_shadow_field(
        variable_name="text", field_type="text", runtime_input_type=TEXT
    )
    assert not is_main_text_field(name="text", field_type="text")
    assert is_main_text_field(name="Input", field_type="text")
    assert is_main_text_field(name="indata_text", field_type=None)
    # A field of another type on the name is not the main text.
    assert not is_main_text_field(name="input", field_type="select")


@pytest.mark.parametrize(
    ("declared", "free"),
    [
        ([], "input"),
        (["tone"], "input"),
        (["input"], "indata_text"),
        (["Input", "tone"], "indata_text"),
        (["indata_text"], "input"),
        (["input", "indata_text"], None),
        (["INPUT", "Indata_Text", "tone"], None),
    ],
)
def test_the_free_main_text_name_never_collides_with_a_declared_field(
    declared: list[str], free: str | None
) -> None:
    assert free_main_text_name(declared) == free


@pytest.mark.parametrize(
    ("fields", "elected"),
    [
        ([], None),
        ([("tone", "text")], None),
        ([("tone", "text"), ("input", "text")], "input"),
        ([("indata_text", "text"), ("input", "text")], "input"),
        ([("Indata_Text", "text"), ("tone", "text")], "Indata_Text"),
        # A field of another type on a main-text name is never the main text.
        ([("input", "select"), ("indata_text", "text")], "indata_text"),
        ([("input", "select"), ("indata_text", "select")], None),
        # `text` is a payload key the form schema rejects.
        ([("text", "text"), ("tone", "text")], None),
    ],
)
def test_exactly_one_main_text_field_is_elected_in_the_fixed_name_order(
    fields: list[tuple[str, str]], elected: str | None
) -> None:
    assert elect_main_text_field(fields) == elected


def test_a_second_main_text_name_beside_others_is_an_ordinary_field() -> None:
    fields = [
        ("tone", "text"),
        ("input", "text"),
        ("indata_text", "text"),
        ("text", "text"),
    ]

    # Only `text` (rejected by the form schema) is dropped; both candidates stay
    # declared, and only the elected one is the main text.
    assert dropped_primary_field_names(runtime_input_type=TEXT, fields=fields) == {
        "text"
    }
    assert elect_main_text_field(fields) == "input"
    # Alone, every primary-looking field duplicates the text box.
    assert dropped_primary_field_names(
        runtime_input_type=TEXT,
        fields=[("input", "text"), ("indata_text", "text"), ("text", "text")],
    ) == {"input", "indata_text", "text"}


@pytest.mark.parametrize(
    ("provenances", "user_action"),
    [
        (("user_confirmed", "user_confirmed"), True),
        (("model_proposed", "model_proposed"), False),
        (("user_confirmed", "model_proposed"), False),
        (("runtime_inferred", "user_confirmed"), False),
    ],
)
def test_a_main_text_name_collision_is_the_persons_only_when_they_confirmed_the_fields(
    provenances: tuple[str, str], user_action: bool
) -> None:
    fields = [
        ("input", "select", provenances[0]),
        ("indata_text", "select", provenances[1]),
        ("tone", "text", "user_confirmed"),
    ]

    collision = main_text_name_collision(runtime_input_type=TEXT, fields=fields)

    assert collision is not None
    assert collision.names == ("input", "indata_text")
    assert collision.user_action is user_action


@pytest.mark.parametrize(
    "fields",
    [
        [("input", "select", "user_confirmed"), ("tone", "text", "user_confirmed")],
        [
            ("input", "text", "user_confirmed"),
            ("indata_text", "select", "user_confirmed"),
        ],
        [("tone", "text", "user_confirmed")],
    ],
)
def test_there_is_no_collision_while_a_name_is_free_or_a_field_is_elected(
    fields: list[tuple[str, str, str]],
) -> None:
    assert main_text_name_collision(runtime_input_type=TEXT, fields=fields) is None


def test_a_reserved_name_beside_other_fields_is_not_a_place_for_the_main_text() -> None:
    fields = [("tone", "text"), ("text", "text")]

    assert main_text_is_a_field(runtime_input_type=TEXT, fields=fields)
    assert main_text_has_no_place(runtime_input_type=TEXT, fields=fields)
