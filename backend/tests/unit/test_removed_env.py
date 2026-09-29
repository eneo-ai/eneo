import contextlib
import logging

import pytest
from pydantic import ValidationError

from eneo.main.config import Settings
from eneo.main.removed_env import (
    REMOVED_VARIABLES,
    UPGRADE_GUIDE_URL,
    check_removed_variables,
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in REMOVED_VARIABLES:
        monkeypatch.delenv(variable.name, raising=False)
        if variable.replacement:
            monkeypatch.delenv(variable.replacement, raising=False)


def test_renamed_variable_without_replacement_stops_startup(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        check_removed_variables({"INTRIC_SUPER_API_KEY": "old"}, {})

    assert exit_info.value.code == 1
    assert "Rename it to ENEO_SUPER_API_KEY" in caplog.text
    assert UPGRADE_GUIDE_URL in caplog.text


def test_value_from_env_file_counts_as_set() -> None:
    with pytest.raises(SystemExit):
        check_removed_variables({}, {"INTRIC_SUPER_API_KEY".lower(): "old"})


def test_renamed_variable_next_to_its_replacement_only_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)

    check_removed_variables(
        {"INTRIC_SUPER_API_KEY": "old"}, {"eneo_super_api_key": "new"}
    )

    assert (
        "INTRIC_SUPER_API_KEY is ignored because ENEO_SUPER_API_KEY is set"
        in caplog.text
    )


@pytest.mark.parametrize(
    "name", ["ENEO_SUPER_DUPER_API_KEY", "INTRIC_SUPER_DUPER_API_KEY"]
)
def test_variable_without_replacement_logs_an_error(
    name: str, caplog: pytest.LogCaptureFixture
) -> None:
    check_removed_variables({name: "old"}, {})

    [record] = caplog.records
    assert record.levelno == logging.ERROR
    assert name in record.getMessage()
    assert "`modules` permission" in record.getMessage()


@pytest.mark.parametrize("value", ["", "   "])
def test_empty_values_are_ignored(value: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)

    check_removed_variables(
        {"INTRIC_SUPER_API_KEY": value, "ENEO_SUPER_DUPER_API_KEY": value}, {}
    )

    assert caplog.records == []


def test_settings_refuses_a_removed_variable_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INTRIC_SUPER_API_KEY", "old")

    with pytest.raises(SystemExit):
        Settings(_env_file=None)


def test_settings_refuses_a_removed_variable_from_an_env_file(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("INTRIC_SUPER_API_KEY=old\n", encoding="utf-8")

    with pytest.raises(SystemExit):
        Settings(_env_file=env_file)


@pytest.mark.parametrize("replacement_in_env_file", [True, False])
def test_settings_only_warns_when_the_replacement_is_also_set(
    replacement_in_env_file: bool,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    lines = ["INTRIC_SUPER_API_KEY=old"]
    if replacement_in_env_file:
        lines.append("ENEO_SUPER_API_KEY=new")
    else:
        monkeypatch.setenv("ENEO_SUPER_API_KEY", "new")
    env_file = tmp_path / ".env"
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # This minimal environment may lack required settings; those are validated
    # after the removed-variable check, which must not exit.
    with contextlib.suppress(ValidationError):
        Settings(_env_file=env_file)

    assert (
        "INTRIC_SUPER_API_KEY is ignored because ENEO_SUPER_API_KEY is set"
        in caplog.text
    )


# Every crawler setting of the tidy branch that the merged Settings no longer
# has: (name, old default, a different value, the settings that replace it).
TENANT_LIMIT = ("CRAWL_JOB_TENANT_CONCURRENCY_LIMIT",)
RETIRED_CRAWLER_SETTINGS = [
    ("TENANT_WORKER_CONCURRENCY_LIMIT", "4", "12", TENANT_LIMIT),
    ("TENANT_WORKER_SEMAPHORE_TTL_SECONDS", "39600", "7200", ()),
    ("USING_CRAWL", "true", "false", ()),
    ("CRAWL_FEEDER_ENABLED", "true", "false", ()),
    ("CRAWL_FEEDER_INTERVAL_SECONDS", "10", "30", ()),
    ("CRAWL_FEEDER_BATCH_SIZE", "10", "50", ()),
    ("ORPHAN_CRAWL_RUN_TIMEOUT_HOURS", "12", "24", ()),
    ("CRAWL_STALE_THRESHOLD_MINUTES", "30", "5", ()),
    ("CRAWL_PAGE_MAX_RETRIES", "3", "9", ()),
    ("CRAWL_PAGE_RETRY_DELAY", "1.0", "2.5", ()),
    ("CRAWL_JOB_MAX_AGE_SECONDS", "1800", "60", ()),
]
RETIRED_NAMES = [name for name, *_ in RETIRED_CRAWLER_SETTINGS]


def test_the_table_covers_every_retired_crawler_setting() -> None:
    registered = {v.name: v for v in REMOVED_VARIABLES if v.old_default is not None}

    assert set(registered) == set(RETIRED_NAMES)
    for name, default, _other, replaced_by in RETIRED_CRAWLER_SETTINGS:
        assert registered[name].old_default == default
        assert registered[name].replaced_by == replaced_by
        assert name.lower() not in Settings.model_fields


def test_only_a_setting_that_controls_the_same_thing_names_a_replacement() -> None:
    # The feeder interval and batch size paced dispatch; a concurrency ceiling
    # cannot reproduce either, so they are not configurable any more.
    with_replacement = {
        name for name, *_rest, replaced_by in RETIRED_CRAWLER_SETTINGS if replaced_by
    }

    assert with_replacement == {"TENANT_WORKER_CONCURRENCY_LIMIT"}


@pytest.mark.parametrize(
    ("name", "default", "_other", "_replaced_by"), RETIRED_CRAWLER_SETTINGS
)
def test_a_retired_crawler_setting_at_its_old_default_only_warns(
    name: str,
    default: str,
    _other: str,
    _replaced_by: tuple[str, ...],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)

    check_removed_variables({name: default}, {})

    [record] = caplog.records
    assert record.levelno == logging.WARNING
    assert f"{name} is no longer read" in record.getMessage()
    assert "changes nothing" in record.getMessage()


@pytest.mark.parametrize(
    ("name", "default", "other", "replaced_by"), RETIRED_CRAWLER_SETTINGS
)
def test_a_retired_crawler_setting_at_another_value_stops_startup(
    name: str,
    default: str,
    other: str,
    replaced_by: tuple[str, ...],
    caplog: pytest.LogCaptureFixture,
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        check_removed_variables({name: other}, {})

    assert exit_info.value.code == 1
    assert f"{name}={other} is no longer read" in caplog.text
    assert f"old default was {default}" in caplog.text
    if replaced_by:
        assert f"Set {' or '.join(replaced_by)} instead and remove it" in caplog.text
    else:
        assert "no longer configurable; remove it" in caplog.text
    assert UPGRADE_GUIDE_URL in caplog.text


@pytest.mark.parametrize(
    ("name", "spelling", "is_default"),
    [
        ("USING_CRAWL", "TRUE", True),
        ("USING_CRAWL", "1", True),
        ("USING_CRAWL", "0", False),
        ("USING_CRAWL", "no", False),
        ("CRAWL_PAGE_RETRY_DELAY", "1", True),
        ("CRAWL_PAGE_RETRY_DELAY", "1.5", False),
        ("TENANT_WORKER_CONCURRENCY_LIMIT", "0", False),
        ("TENANT_WORKER_CONCURRENCY_LIMIT", "many", False),
    ],
)
def test_values_are_compared_as_the_old_setting_read_them(
    name: str, spelling: str, is_default: bool
) -> None:
    if is_default:
        check_removed_variables({name: spelling}, {})
    else:
        with pytest.raises(SystemExit):
            check_removed_variables({name: spelling}, {})


def test_every_refused_setting_is_reported_together(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with pytest.raises(SystemExit):
        check_removed_variables(
            {"USING_CRAWL": "false", "CRAWL_JOB_MAX_AGE_SECONDS": "60"}, {}
        )

    assert "USING_CRAWL=false" in caplog.text
    assert "CRAWL_JOB_MAX_AGE_SECONDS=60" in caplog.text


@pytest.mark.parametrize(
    ("name", "value"), [("USING_CRAWL", "false"), ("CRAWL_JOB_MAX_AGE_SECONDS", "60")]
)
def test_settings_refuses_a_retired_crawler_value_from_an_env_file(
    name: str, value: str, tmp_path
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f"{name}={value}\n", encoding="utf-8")

    with pytest.raises(SystemExit):
        Settings(_env_file=env_file)


def test_settings_accepts_retired_crawler_values_at_their_old_defaults(
    tmp_path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "TENANT_WORKER_CONCURRENCY_LIMIT=4\nUSING_CRAWL=true\n", encoding="utf-8"
    )

    # Required settings may be missing here; they are validated after the
    # removed-variable check, which must not exit.
    with contextlib.suppress(ValidationError):
        Settings(_env_file=env_file)

    assert "TENANT_WORKER_CONCURRENCY_LIMIT is no longer read" in caplog.text
    assert "USING_CRAWL is no longer read" in caplog.text
