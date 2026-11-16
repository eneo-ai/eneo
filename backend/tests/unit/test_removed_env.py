import contextlib
import logging

import pytest
from pydantic import ValidationError

from eneo.main.config import Settings
from eneo.main.removed_env import (
    OIDC_MIGRATION_GUIDE_URL,
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


MOBILITYGUARD_RENAMES = [
    ("MOBILITYGUARD_DISCOVERY_ENDPOINT", "OIDC_DISCOVERY_ENDPOINT"),
    ("MOBILITYGUARD_CLIENT_ID", "OIDC_CLIENT_ID"),
    ("MOBILITYGUARD_CLIENT_SECRET", "OIDC_CLIENT_SECRET"),
    ("MOBILITYGUARD_TENANT_ID", "OIDC_TENANT_ID"),
]


@pytest.mark.parametrize("name, replacement", MOBILITYGUARD_RENAMES)
def test_mobilityguard_variable_without_its_oidc_name_stops_startup(
    name: str, replacement: str, caplog: pytest.LogCaptureFixture
) -> None:
    with pytest.raises(SystemExit):
        check_removed_variables({name: "old"}, {})

    assert f"Rename it to {replacement}" in caplog.text
    assert OIDC_MIGRATION_GUIDE_URL in caplog.text
    assert "Eneo 2.2" not in caplog.text


@pytest.mark.parametrize("name, replacement", MOBILITYGUARD_RENAMES)
def test_mobilityguard_variable_next_to_its_oidc_name_only_warns(
    name: str, replacement: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)

    check_removed_variables({name: "old"}, {replacement.lower(): "new"})

    assert f"{name} is ignored because {replacement} is set" in caplog.text


def test_settings_refuses_a_mobilityguard_variable_from_an_env_file(
    tmp_path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("MOBILITYGUARD_CLIENT_ID=old\n", encoding="utf-8")

    with pytest.raises(SystemExit):
        Settings(_env_file=env_file)
