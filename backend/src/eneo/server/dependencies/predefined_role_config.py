"""Read role templates without importing application or worker services."""

from pathlib import Path
from typing import Any

import yaml


def load_predefined_roles_from_config() -> list[dict[str, Any]]:
    config_path = Path(__file__).with_name("predefined_roles.yml")
    with config_path.open() as file:
        return yaml.safe_load(file)["roles"]
