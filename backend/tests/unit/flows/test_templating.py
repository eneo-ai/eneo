"""Deterministic template substitution for step inputs."""

import pytest

from eneo.flows.templating import (
    Reference,
    StepOutput,
    TemplateContext,
    TemplateError,
    extract_references,
    parse_reference,
    render_template,
)


def test_parse_reference_shapes():
    assert parse_reference("previous") == Reference(raw="previous", source="previous")
    assert parse_reference("form.topic") == Reference(
        raw="form.topic", source="form", key="topic"
    )
    assert parse_reference("steps.draft") == Reference(
        raw="steps.draft", source="steps", key="draft"
    )
    nested = parse_reference("steps.draft.json.items.0.title")
    assert nested.key == "draft"
    assert nested.json_path == ("items", "0", "title")
    assert nested.wants_json


@pytest.mark.parametrize("raw", ["steps", "form", "steps.a.b", "nope.x", "form.a.b"])
def test_unknown_reference_shapes_raise(raw):
    with pytest.raises(TemplateError):
        parse_reference(raw)


def test_extract_references_in_order_of_appearance():
    refs = extract_references("{{ form.a }} then {{steps.b}} and {{previous}}")
    assert [ref.raw for ref in refs] == ["form.a", "steps.b", "previous"]
    assert extract_references("no references here") == []


def _context() -> TemplateContext:
    return TemplateContext(
        form={"topic": "harbours", "count": "3"},
        steps={
            "draft": StepOutput(text="draft text"),
            "facts": StepOutput(
                text='{"items": [{"title": "One"}], "n": 2}',
                value={"items": [{"title": "One"}], "n": 2, "tags": ["x", "y"]},
            ),
        },
        previous="the last output",
    )


def test_render_substitutes_every_reference_kind():
    rendered = render_template(
        "Topic {{form.topic}} ({{ form.count }}): {{steps.draft}} / "
        "{{steps.facts.json.items.0.title}} / {{steps.facts.json.n}} / {{previous}}",
        _context(),
    )
    assert rendered == "Topic harbours (3): draft text / One / 2 / the last output"


def test_render_serializes_json_containers_as_json():
    rendered = render_template("{{steps.facts.json.items}}", _context())
    assert rendered == '[\n  {\n    "title": "One"\n  }\n]'


def test_render_leaves_plain_text_untouched():
    assert render_template("{ not a reference }", _context()) == "{ not a reference }"


@pytest.mark.parametrize(
    "template, message",
    [
        ("{{form.missing}}", "Form field 'missing' has no value."),
        ("{{steps.nothing}}", "Step 'nothing' has not produced output."),
        ("{{steps.draft.json.a}}", "produced no JSON"),
        ("{{steps.facts.json.missing}}", "key 'missing' is missing"),
        ("{{steps.facts.json.items.9}}", "not a valid list index"),
        ("{{steps.facts.json.n.deeper}}", "cannot read 'deeper' from a scalar value"),
    ],
)
def test_render_errors_name_the_problem(template, message):
    with pytest.raises(TemplateError, match=message):
        render_template(template, _context())


def test_a_list_of_values_renders_as_bullet_lines():
    context = TemplateContext(form={})
    context.steps["klassa"] = StepOutput(
        text="{}",
        value={
            "atgarder": ["Kontrollera ansökan", "Begär medgivande"],
            "nested": [{"a": 1}],
            "empty": [],
        },
    )
    assert render_template("{{steps.klassa.json.atgarder}}", context) == (
        "- Kontrollera ansökan\n- Begär medgivande"
    )
    assert render_template("{{steps.klassa.json.nested}}", context).startswith("[")
    assert render_template("{{steps.klassa.json.empty}}", context) == "[]"
