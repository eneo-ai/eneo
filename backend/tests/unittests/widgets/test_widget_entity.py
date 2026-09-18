from uuid import uuid4

import pytest

from eneo.main.exceptions import BadRequestException
from eneo.widgets.domain.widget import (
    DEFAULT_AI_DISCLOSURE,
    BotProtection,
    Widget,
    WidgetLanguage,
    WidgetLimits,
    WidgetStatus,
    WidgetTexts,
    generate_public_id,
    is_public_id,
    normalize_allowed_origins,
)


def _widget(**overrides) -> Widget:
    base = dict(
        tenant_id=uuid4(),
        space_id=uuid4(),
        target_id=uuid4(),
        name="Kommunens assistent",
    )
    base.update(overrides)
    return Widget.create(**base)


def test_public_id_has_prefix_and_is_unique():
    first, second = generate_public_id(), generate_public_id()
    assert is_public_id(first) and is_public_id(second)
    assert first != second
    assert not is_public_id("wgt_short")
    assert not is_public_id(str(uuid4()))


def test_create_uses_language_specific_disclosure():
    assert _widget().texts.subtitle == DEFAULT_AI_DISCLOSURE["sv"]
    assert (
        _widget(language=WidgetLanguage.EN).texts.subtitle
        == DEFAULT_AI_DISCLOSURE["en"]
    )


@pytest.mark.parametrize(
    "origins,expected",
    [
        (["https://www.kommun.se/"], ["https://www.kommun.se"]),
        (["HTTPS://WWW.Kommun.SE", "https://www.kommun.se"], ["https://www.kommun.se"]),
        (["https://*.kommun.se"], ["https://*.kommun.se"]),
        (["http://localhost:*"], ["http://localhost:*"]),
        (["http://localhost:5173"], ["http://localhost:5173"]),
    ],
)
def test_allowed_origins_are_normalised_and_deduplicated(origins, expected):
    assert normalize_allowed_origins(origins) == expected


@pytest.mark.parametrize(
    "origin",
    [
        "www.kommun.se",
        "ftp://kommun.se",
        "https://www.kommun.se/start",
        "https://www.kommun.se?x=1",
        "https://user@www.kommun.se",
        "https://",
    ],
)
def test_invalid_allowed_origins_are_rejected(origin):
    with pytest.raises(ValueError):
        normalize_allowed_origins([origin])


def test_too_many_allowed_origins_are_rejected():
    origins = [f"https://site{i}.kommun.se" for i in range(21)]
    with pytest.raises(ValueError):
        normalize_allowed_origins(origins)


def test_texts_are_cleaned_and_bounded():
    texts = WidgetTexts(
        title="  Fråga   oss ", suggested_questions=["  Öppettider? ", "Bygglov"]
    )
    assert texts.title == "Fråga oss"
    assert texts.suggested_questions == ["Öppettider?", "Bygglov"]
    with pytest.raises(ValueError):
        WidgetTexts(suggested_questions=[" "])
    with pytest.raises(ValueError):
        WidgetTexts(suggested_questions=["a", "b", "c", "d", "e"])
    with pytest.raises(ValueError):
        WidgetTexts(footer_link_url="kommun.se/integritet")
    assert WidgetTexts(footer_link_url="  ").footer_link_url is None


def test_activation_blockers_cover_origins_disclosure_and_target():
    widget = _widget()
    widget.texts = WidgetTexts(subtitle="")
    assert widget.activation_blockers(target_published=False) == [
        "allowed_origins_empty",
        "subtitle_empty",
        "target_not_published",
    ]
    widget.allowed_origins = ["https://www.kommun.se"]
    widget.texts = WidgetTexts()
    assert widget.activation_blockers(target_published=True) == []


def test_status_transitions_and_token_generation():
    widget = _widget()
    by = uuid4()
    assert widget.status == WidgetStatus.DRAFT

    with pytest.raises(BadRequestException):
        widget.pause()

    widget.activate(by=by)
    assert widget.status == WidgetStatus.ACTIVE
    assert widget.activated_by_user_id == by
    assert widget.activated_at is not None
    assert widget.token_generation == 0

    with pytest.raises(BadRequestException):
        widget.activate(by=by)

    widget.pause()
    assert widget.status == WidgetStatus.PAUSED
    assert widget.paused_at is not None
    assert widget.token_generation == 1

    widget.activate(by=by)
    assert widget.status == WidgetStatus.ACTIVE
    assert widget.paused_at is None

    widget.archive()
    assert widget.status == WidgetStatus.ARCHIVED
    assert widget.token_generation == 2
    with pytest.raises(BadRequestException):
        widget.archive()
    with pytest.raises(BadRequestException):
        widget.apply_update({"name": "x"})


def test_apply_update_bumps_generation_only_for_visitor_facing_fields():
    widget = _widget()
    assert widget.apply_update({"name": "Nytt namn"}) is False
    assert widget.token_generation == 0

    assert widget.apply_update({"allowed_origins": ["https://www.kommun.se"]}) is True
    assert widget.token_generation == 1

    # Same value again: no bump.
    assert widget.apply_update({"allowed_origins": ["https://www.kommun.se/"]}) is False
    assert widget.token_generation == 1

    assert (
        widget.apply_update({"limits": WidgetLimits(daily_token_budget=10_000)}) is True
    )
    assert widget.apply_update({"bot_protection": BotProtection.NONE}) is True
    assert widget.token_generation == 3

    with pytest.raises(BadRequestException):
        widget.apply_update({"status": WidgetStatus.ACTIVE})
    with pytest.raises(BadRequestException):
        widget.apply_update({"name": "   "})


def test_theme_header_colour_and_logo_are_validated():
    from eneo.widgets.domain.widget import WidgetTheme

    theme = WidgetTheme(
        header_color=" #abcdef ", logo_url=" https://kommun.se/logo.svg "
    )
    assert theme.header_color == "#ABCDEF"
    assert theme.logo_url == "https://kommun.se/logo.svg"
    assert WidgetTheme(header_color="", logo_url="").header_color is None
    assert WidgetTheme(header_color="", logo_url="").logo_url is None
    dark = WidgetTheme(primary_color_dark="#abcdef", header_color_dark="")
    assert dark.primary_color_dark == "#ABCDEF"
    assert dark.header_color_dark is None
    with pytest.raises(ValueError):
        WidgetTheme(primary_color_dark="red")
    with pytest.raises(ValueError):
        WidgetTheme(header_color="blue")
    with pytest.raises(ValueError):
        WidgetTheme(logo_url="javascript:alert(1)")
