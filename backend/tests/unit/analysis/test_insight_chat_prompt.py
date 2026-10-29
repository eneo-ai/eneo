"""The insights system prompt fixes time, calendar rules and tool routing."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from eneo.analysis.insight_chat_prompt import build_insights_system_prompt

NOW = datetime(2026, 9, 8, 14, 30, tzinfo=ZoneInfo("Europe/Stockholm"))


def _prompt(**overrides):
    kwargs = dict(
        now=NOW,
        timezone="Europe/Stockholm",
        target_kind="assistant",
        target_name="Bygglov",
        selected_range=None,
    )
    kwargs.update(overrides)
    return build_insights_system_prompt(**kwargs)


def test_names_the_target_current_time_weekday_and_timezone():
    prompt = _prompt()

    assert "assistant 'Bygglov'" in prompt
    assert "2026-09-08T14:30+02:00 (Tuesday), timezone Europe/Stockholm" in prompt


def test_group_chat_wording():
    assert "group chat 'Team'" in _prompt(target_kind="group_chat", target_name="Team")


def test_relative_date_rules_and_tool_routing_are_spelled_out():
    prompt = _prompt()

    assert '"yesterday" ("igår") = the previous local calendar day' in prompt
    assert "Monday-to-Monday" in prompt
    assert "usage_summary for anything about volume" in prompt
    assert "top_questions for the most common" in prompt
    assert "list_questions to read what people actually asked" in prompt
    assert "(session <uuid>)" in prompt
    assert "Always call at least one tool before answering" in prompt


def test_default_window_falls_back_to_last_30_days():
    assert "use the last 30 days ending now" in _prompt()


def test_default_window_uses_the_selected_range_when_given():
    prompt = _prompt(selected_range=(date(2026, 8, 1), date(2026, 8, 31)))

    assert "selects 2026-08-01 to 2026-08-31" in prompt
    assert "last 30 days" not in prompt
