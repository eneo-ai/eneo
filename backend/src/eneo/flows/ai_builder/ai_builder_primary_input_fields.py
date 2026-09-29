from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from eneo.flows.flow_authoring_spec import (
    FormFieldSpec,
    InputType,
)
from eneo.flows.flow_metadata import validate_form_field_runtime_name
from eneo.main.exceptions import BadRequestException

_PRIMARY_INPUT_FIELD_ALIASES: dict[InputType, frozenset[str]] = {
    InputType.TEXT: frozenset({"text", "input", "indata_text"}),
    InputType.JSON: frozenset({"json", "input_json", "indata_json"}),
    InputType.DOCUMENT: frozenset(
        {"document", "documents", "input_document", "indata_document"}
    ),
    InputType.FILE: frozenset({"file", "files", "input_file", "indata_file"}),
    InputType.AUDIO: frozenset(
        {
            "audio",
            "input_audio",
            "indata_audio",
            "transcript",
            "transcription",
            "transcription_text",
            "transcribed_text",
            "transkribering",
            "transkription",
            "transkription_text",
        }
    ),
}


def _usable_form_field_name(name: str) -> bool:
    """Whether the form-schema contract allows a field this name (it rejects
    namespace heads, runtime payload keys such as ``text``, and step aliases)."""

    try:
        validate_form_field_runtime_name(0, name)
    except BadRequestException:
        return False
    return True


# The names a text flow's main text can carry as a form field, in the order the
# compiler tries them: the primary-input names the form-schema contract allows.
# The first free one is declared; a confirmed field of another type on a name
# here makes it unavailable, never replaced.
MAIN_TEXT_FIELD_NAMES: tuple[str, ...] = tuple(
    name
    for name in ("input", "indata_text", "text")
    if name in _PRIMARY_INPUT_FIELD_ALIASES[InputType.TEXT]
    and _usable_form_field_name(name)
)


def primary_input_shadow_alias_input_types() -> frozenset[InputType]:
    return frozenset(_PRIMARY_INPUT_FIELD_ALIASES)


def primary_input_reserved_names(runtime_input_type: InputType) -> tuple[str, ...]:
    """The form field names a flow keeps for the run input of this type."""

    return tuple(sorted(_PRIMARY_INPUT_FIELD_ALIASES.get(runtime_input_type, ())))


def is_primary_runtime_input_shadow_field(
    *,
    variable_name: str,
    field_type: str | None,
    runtime_input_type: InputType | None,
) -> bool:
    """Return true when a form field duplicates the flow's primary run input.

    AI Builder form fields represent secondary runtime parameters such as
    audience, tone, case id, or report level. The primary material the flow
    processes is already supplied through Flow runtime input, so a form
    field named after that primary input would create duplicate UX and token
    usage.
    """

    if runtime_input_type is None:
        return False
    normalized_name = variable_name.strip().casefold()
    if normalized_name not in _PRIMARY_INPUT_FIELD_ALIASES.get(
        runtime_input_type, frozenset()
    ):
        return False

    normalized_type = (field_type or "text").strip().casefold()
    return normalized_type in {"", "text"}


def is_main_text_field(*, name: str, field_type: str | None) -> bool:
    """Whether a form field can carry a text flow's main text: a text field
    named like the main input, on a name the form-schema contract allows."""

    return name.strip().casefold() in MAIN_TEXT_FIELD_NAMES and (
        field_type or "text"
    ).strip().casefold() in {"", "text"}


def main_text_is_a_field(
    *,
    runtime_input_type: InputType | None,
    fields: Iterable[tuple[str, str | None]],
) -> bool:
    """Whether a text flow's main text has to be a form field (name, type).

    The run dialog shows its one text box only for a run with no form fields.
    So when a text flow also collects other fields, its main text is a field: one
    that ``is_main_text_field`` is kept, and required. A primary-looking field
    that cannot be it (``text``, a name the form schema rejects) is dropped or,
    when confirmed, renamed; alone a primary-looking field duplicates the text
    box and is dropped. One rule for create and edit."""

    return runtime_input_type is InputType.TEXT and any(
        not is_primary_runtime_input_shadow_field(
            variable_name=name, field_type=field_type, runtime_input_type=InputType.TEXT
        )
        for name, field_type in fields
    )


def elect_main_text_field(fields: Iterable[tuple[str, str | None]]) -> str | None:
    """The one field that is the main text: the first declared text field on a
    main-text name, in the fixed name order. Only it is required and bound as the
    main text; another field on a main-text name stays an ordinary field. One
    election for create and edit; the declared name is returned as written."""

    declared = list(fields)
    for candidate in MAIN_TEXT_FIELD_NAMES:
        for name, field_type in declared:
            if name.strip().casefold() == candidate and is_main_text_field(
                name=name, field_type=field_type
            ):
                return name
    return None


def main_text_has_no_place(
    *,
    runtime_input_type: InputType | None,
    fields: Iterable[tuple[str, str | None]],
) -> bool:
    """A text flow that collects form fields but none that can carry its main text."""

    declared = list(fields)
    return (
        main_text_is_a_field(runtime_input_type=runtime_input_type, fields=declared)
        and elect_main_text_field(declared) is None
    )


def dropped_primary_field_names(
    *,
    runtime_input_type: InputType | None,
    fields: Iterable[tuple[str, str | None]],
) -> frozenset[str]:
    """The declared fields that duplicate the primary input and are dropped, or
    renamed when confirmed. Beside other fields a text flow's main-text names are
    ordinary or elected fields, so only a name the form schema rejects (``text``)
    is left; alone, every primary-looking field duplicates the text box."""

    declared = list(fields)
    looking = {
        name
        for name, field_type in declared
        if is_primary_runtime_input_shadow_field(
            variable_name=name,
            field_type=field_type,
            runtime_input_type=runtime_input_type,
        )
    }
    if main_text_is_a_field(runtime_input_type=runtime_input_type, fields=declared):
        return frozenset(
            name
            for name in looking
            if not is_main_text_field(name=name, field_type="text")
        )
    return frozenset(looking)


def free_main_text_name(declared_names: Iterable[str]) -> str | None:
    """The first main-text name no declared field holds (any type, any case),
    or None when every one is taken."""

    taken = {name.strip().casefold() for name in declared_names}
    return next((name for name in MAIN_TEXT_FIELD_NAMES if name not in taken), None)


@dataclass(frozen=True, slots=True)
class MainTextNameCollision:
    """Every name for the main text is held by a field of another type."""

    names: tuple[str, ...]
    # Only the person can rename fields they confirmed; the model renames its own.
    user_action: bool


def main_text_name_collision(
    *,
    runtime_input_type: InputType | None,
    fields: Sequence[tuple[str, str | None, str | None]],
) -> MainTextNameCollision | None:
    """The collision that stops the compiler declaring the main text, else None.

    ``fields`` are (name, type, provenance). The compiler never replaces or
    retypes a declared field: with no free name a field has to be renamed, by the
    person when every colliding field is user-confirmed, else by the model."""

    declared = [(name, field_type) for name, field_type, _ in fields]
    names = [name for name, _ in declared]
    if (
        not main_text_has_no_place(
            runtime_input_type=runtime_input_type, fields=declared
        )
        or free_main_text_name(names) is not None
    ):
        return None
    colliding = [
        provenance
        for name, _, provenance in fields
        if name.strip().casefold() in MAIN_TEXT_FIELD_NAMES
    ]
    return MainTextNameCollision(
        names=tuple(
            name for name in names if name.strip().casefold() in MAIN_TEXT_FIELD_NAMES
        ),
        user_action=all(provenance == "user_confirmed" for provenance in colliding),
    )


def declared_main_text_field(*, name: str, ui_language: str | None) -> FormFieldSpec:
    """The required text field the compiler declares for a text flow's main text."""

    english = ui_language is not None and ui_language.casefold().startswith("en")
    return FormFieldSpec(
        name=name,
        label="Text to process" if english else "Text att bearbeta",
        type="text",
        required=True,
    )


def main_text_beside_fields_detail(
    *, can_declare_fields: bool, fields: Iterable[tuple[str, str | None]]
) -> str:
    """Why an edit is refused, and what repairs it, as the model reads it; the
    remedy follows the declared fields (name, type): read the elected main-text
    field, declare one on the first free name, or rename a field holding them."""

    declared = list(fields)
    elected = elect_main_text_field(declared)
    field_name = free_main_text_name(name for name, _ in declared)
    if elected is not None:
        remedy = (
            f"The main text is the form field `{elected}`: the step reads it "
            "({{ flow_input." + elected + " }}; uses_form_fields on a modify) "
            "instead of the run text."
        )
    elif field_name is None:
        remedy = (
            f"Every name for it ({', '.join(f'`{n}`' for n in MAIN_TEXT_FIELD_NAMES)}) "
            "is taken by another field: rename that field, remove the form "
            "fields, or ask the person how the main text should be provided."
        )
    elif can_declare_fields:
        remedy = (
            f"Either declare the main text as a required text form field named "
            f"`{field_name}` (the step that reads it lists `{field_name}` in "
            "uses_form_fields), remove the form fields, or ask the person how the "
            "main text should be provided."
        )
    else:
        remedy = (
            "Ask the person how the main text should be provided, for example as "
            f"a required text form field named `{field_name}`, or without the form "
            "fields."
        )
    return (
        "The flow's main text cannot be collected beside form fields: the run "
        "dialog shows its one text box only when the run has no form fields, so "
        f"the flow would run without its main text. {remedy}"
    )


def split_primary_runtime_input_shadow_names(
    *,
    field_names: list[str],
    runtime_input_type: InputType | None,
    kept_names: frozenset[str] = frozenset(),
) -> tuple[list[str], list[str]]:
    """Split step reads into kept and dropped; ``kept_names`` are declared fields
    a shadow-looking name may not be dropped from (see
    ``dropped_primary_field_names``)."""

    kept: list[str] = []
    dropped: list[str] = []
    for field_name in field_names:
        if field_name not in kept_names and is_primary_runtime_input_shadow_field(
            variable_name=field_name,
            field_type="text",
            runtime_input_type=runtime_input_type,
        ):
            dropped.append(field_name)
            continue
        kept.append(field_name)
    return kept, dropped


__all__ = [
    "MAIN_TEXT_FIELD_NAMES",
    "MainTextNameCollision",
    "declared_main_text_field",
    "dropped_primary_field_names",
    "elect_main_text_field",
    "free_main_text_name",
    "is_main_text_field",
    "is_primary_runtime_input_shadow_field",
    "main_text_name_collision",
    "main_text_beside_fields_detail",
    "main_text_has_no_place",
    "main_text_is_a_field",
    "primary_input_shadow_alias_input_types",
    "primary_input_reserved_names",
    "split_primary_runtime_input_shadow_names",
]
