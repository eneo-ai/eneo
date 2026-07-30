from __future__ import annotations

import pytest

from eneo.flows.domain.runtime_input import parse_runtime_input_config
from eneo.main.exceptions import BadRequestException


def test_parse_runtime_input_config_accepts_valid_json_contract_values() -> None:
    config = parse_runtime_input_config(
        {
            "runtime_input": {
                "enabled": True,
                "required": True,
                "max_files": 2,
                "input_format": "document",
                "execution_mode": "per_source",
            }
        }
    )

    assert config.enabled is True
    assert config.required is True
    assert config.max_files == 2
    assert config.input_format == "document"
    assert config.execution_mode == "per_source"


def test_parse_runtime_input_config_keeps_single_call_file_ceiling_optional() -> None:
    config = parse_runtime_input_config(
        {"runtime_input": {"enabled": True, "execution_mode": "single_call"}}
    )

    assert config.enabled is True
    assert config.max_files is None


@pytest.mark.parametrize(
    ("runtime_input", "expected_enabled"),
    [
        (True, True),
        (False, False),
    ],
)
def test_parse_runtime_input_config_supports_literal_bool_shortcuts(
    runtime_input: bool,
    expected_enabled: bool,
) -> None:
    config = parse_runtime_input_config({"runtime_input": runtime_input})

    assert config.enabled is expected_enabled


@pytest.mark.parametrize(
    "runtime_input",
    [
        {"enabled": "true"},
        {"required": "false"},
        {"max_files": "2"},
        {"max_files": True},
        {"max_files": 0},
        {"max_files": -1},
        {"execution_mode": "per_document"},
        0,
    ],
)
def test_parse_runtime_input_config_rejects_coerced_json_contract_values(
    runtime_input: object,
) -> None:
    with pytest.raises(BadRequestException, match="runtime_input"):
        parse_runtime_input_config({"runtime_input": runtime_input})
