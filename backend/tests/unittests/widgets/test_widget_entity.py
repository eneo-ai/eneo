from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from eneo.database.tables.widgets_table import Widgets
from eneo.main.exceptions import BadRequestException
from eneo.widgets.domain.exceptions import WidgetActivationRequestMissingError
from eneo.widgets.domain.widget import (
    ACTIVATION_REVIEW_FIELDS,
    DEFAULT_AI_DISCLOSURE,
    LIFECYCLE_FIELDS,
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
        # CSP directive syntax must never reach the frame-ancestors header.
        "https://a.com; report-to grp",
        "https://a.com b.com",
        "https://a.com;default-src",
        "https://a.com\ttab",
        "https://exämple.se",
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
    assert WidgetTexts(
        suggested_questions=["a", "b", "c", "d"]
    ).suggested_questions == [
        "a",
        "b",
        "c",
        "d",
    ]
    with pytest.raises(ValueError):
        WidgetTexts(suggested_questions=["a", "b", "c", "d", "e"])
    # The embed page keys the chips by text; a repeat would crash it.
    with pytest.raises(ValueError):
        WidgetTexts(suggested_questions=["Öppettider?", " Öppettider? "])
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


def test_blockers_introduced_count_only_settings_the_edit_changed():
    widget = _widget()
    widget.allowed_origins = ["https://www.kommun.se"]
    before = widget.model_copy(deep=True)
    widget.apply_update({"texts": {**widget.texts.model_dump(), "subtitle": ""}})
    assert widget.blockers_introduced_since(before) == ["subtitle_empty"]

    # Left standing, the empty subtitle does not hold up an unrelated edit,
    # even one that sends the texts group whole.
    before = widget.model_copy(deep=True)
    widget.apply_update(
        {"name": "Ny", "texts": {**widget.texts.model_dump(), "title": "Hej"}}
    )
    assert widget.blockers_introduced_since(before) == []

    before = widget.model_copy(deep=True)
    widget.apply_update({"allowed_origins": []})
    assert widget.blockers_introduced_since(before) == ["allowed_origins_empty"]


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
    # The editor expands shorthand before saving; the API only stores #RRGGBB.
    assert WidgetTheme(primary_color="#AABBCC").primary_color == "#AABBCC"
    with pytest.raises(ValueError):
        WidgetTheme(primary_color="#ABC")
    with pytest.raises(ValueError):
        WidgetTheme(header_color="#abc")
    with pytest.raises(ValueError):
        WidgetTheme(primary_color_dark="red")
    with pytest.raises(ValueError):
        WidgetTheme(header_color="blue")
    with pytest.raises(ValueError):
        WidgetTheme(logo_url="javascript:alert(1)")


def _review_state(widget: Widget) -> dict:
    return {field: getattr(widget, field) for field in ACTIVATION_REVIEW_FIELDS}


_NO_REVIEW = dict.fromkeys(ACTIVATION_REVIEW_FIELDS)


def _activatable_widget() -> Widget:
    widget = _widget()
    widget.apply_update({"allowed_origins": ["https://www.kommun.se"]})
    return widget


def test_activation_can_be_requested_from_draft_or_paused_only():
    by = uuid4()
    widget = _activatable_widget()
    assert widget.request_activation(by=by) is True
    assert widget.activation_requested_by_user_id == by
    assert widget.activation_requested_at is not None

    widget.activate(by=uuid4())
    with pytest.raises(BadRequestException):
        widget.request_activation(by=by)

    widget.pause()
    assert widget.request_activation(by=by) is True

    widget.archive()
    with pytest.raises(BadRequestException):
        widget.request_activation(by=by)


def test_a_repeated_request_changes_nothing_and_a_new_one_clears_a_send_back():
    editor, admin = uuid4(), uuid4()
    widget = _widget()
    first = datetime(2026, 9, 1, tzinfo=timezone.utc)
    assert widget.request_activation(by=editor, now=first) is True
    assert widget.request_activation(by=uuid4()) is False
    assert widget.activation_requested_at == first
    assert widget.activation_requested_by_user_id == editor

    widget.decline_activation_request(by=admin, reason="Lägg till fler källor.")
    assert widget.request_activation(by=editor) is True
    assert widget.activation_declined_at is None
    assert widget.activation_declined_by_user_id is None
    assert widget.activation_decline_reason is None


def test_withdrawing_without_a_pending_request_changes_nothing():
    widget = _widget()
    assert widget.withdraw_activation_request() is False
    assert _review_state(widget) == _NO_REVIEW

    widget.request_activation(by=uuid4())
    assert widget.withdraw_activation_request() is True
    assert _review_state(widget) == _NO_REVIEW


def test_sending_back_needs_a_pending_request():
    widget = _widget()
    with pytest.raises(WidgetActivationRequestMissingError) as refused:
        widget.decline_activation_request(by=uuid4(), reason="Lägg till fler källor.")
    assert refused.value.status_code == 409
    assert refused.value.code == "widget_activation_request_missing"

    admin = uuid4()
    widget.request_activation(by=uuid4())
    widget.decline_activation_request(by=admin, reason="Lägg till fler källor.")
    assert widget.activation_requested_at is None
    assert widget.activation_requested_by_user_id is None
    assert widget.activation_declined_by_user_id == admin
    assert widget.activation_declined_at is not None
    assert widget.activation_decline_reason == "Lägg till fler källor."

    with pytest.raises(WidgetActivationRequestMissingError):
        widget.decline_activation_request(by=admin, reason="Lägg till fler källor.")


@pytest.mark.parametrize("sent_back", [False, True])
def test_activate_and_archive_clear_the_activation_review(sent_back):
    # validate_assignment would reject the status change if the review
    # fields were cleared after it, so passing proves the order.
    widget = _activatable_widget()
    widget.request_activation(by=uuid4())
    if sent_back:
        widget.decline_activation_request(by=uuid4(), reason="Lägg till fler källor.")
    widget.activate(by=uuid4())
    assert widget.status == WidgetStatus.ACTIVE
    assert _review_state(widget) == _NO_REVIEW

    widget.pause()
    widget.request_activation(by=uuid4())
    if sent_back:
        widget.decline_activation_request(by=uuid4(), reason="Lägg till fler källor.")
    widget.archive()
    assert widget.status == WidgetStatus.ARCHIVED
    assert _review_state(widget) == _NO_REVIEW


def test_a_widget_awaiting_activation_is_draft_or_paused_and_not_sent_back():
    now = datetime.now(timezone.utc)
    base = _widget().model_dump()
    with pytest.raises(ValidationError):
        Widget.model_validate(
            base
            | {
                "status": WidgetStatus.ACTIVE,
                "activated_at": now,
                "activation_requested_at": now,
            }
        )
    with pytest.raises(ValidationError):
        Widget.model_validate(
            base
            | {
                "activation_requested_at": now,
                "activation_declined_at": now,
                "activation_decline_reason": "Lägg till fler källor.",
            }
        )

    requested = _widget()
    requested.request_activation(by=uuid4())
    requested.activated_at = now
    with pytest.raises(ValidationError):
        requested.status = WidgetStatus.ACTIVE

    requested = _widget()
    requested.request_activation(by=uuid4())
    with pytest.raises(ValidationError):
        requested.activation_declined_at = now


def test_the_activation_review_is_written_by_every_lifecycle_command():
    assert ACTIVATION_REVIEW_FIELDS <= LIFECYCLE_FIELDS
    assert ACTIVATION_REVIEW_FIELDS <= set(Widget.model_fields)


def test_the_activation_review_round_trips_through_the_row_mapping():
    from eneo.widgets.infrastructure.widget_repo_impl import _to_values, to_entity

    widget = _widget()
    widget.request_activation(by=uuid4())
    widget.decline_activation_request(by=uuid4(), reason="Lägg till fler källor.")
    values = _to_values(widget)
    assert ACTIVATION_REVIEW_FIELDS <= set(values)

    now = datetime.now(timezone.utc)
    row = Widgets(**values, id=uuid4(), revision=0, created_at=now, updated_at=now)
    assert _review_state(to_entity(row)) == _review_state(widget)
