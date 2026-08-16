"""The inline upload ceiling must have exactly one value across the product.

An operator who copies a shipped env template gets whatever that file says, not
the settings-model default. When the two disagree, administrators see an upload
limit they cannot raise from any admin page, because the env value caps both the
deployment policy and every tenant limit derived from it.
"""

import re
from pathlib import Path

from eneo.object_content.configuration import ObjectContentCoreSettings

REPO_ROOT = Path(__file__).resolve().parents[3]
SHIPPED_ENV_TEMPLATES = (
    REPO_ROOT / "docs" / "deployment" / "env_backend.template",
    REPO_ROOT / "backend" / ".env.template",
)
SETTING_NAME = "OBJECT_CONTENT_INLINE_MAXIMUM_BYTES"


def _assignment(template: Path, name: str) -> int:
    pattern = re.compile(rf"^{name}=(\d+)", re.MULTILINE)
    matches = pattern.findall(template.read_text(encoding="utf-8"))
    assert matches, f"{template} does not set {name}"
    assert len(set(matches)) == 1, f"{template} sets {name} more than once: {matches}"
    return int(matches[0])


def test_shipped_env_templates_carry_the_inline_ceiling_default() -> None:
    # The declared default, not a resolved instance: instantiating the settings
    # would read this machine's environment and compare a template against it.
    declared_default = ObjectContentCoreSettings.model_fields[
        "inline_maximum_bytes"
    ].default

    for template in SHIPPED_ENV_TEMPLATES:
        assert _assignment(template, SETTING_NAME) == declared_default, (
            f"{template} would deploy a different inline ceiling than the "
            "settings-model default, so administrators could not raise upload "
            "limits to the documented maximum."
        )
