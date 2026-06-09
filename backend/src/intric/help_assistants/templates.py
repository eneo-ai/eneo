"""Code-owned registry of installable Help Assistant templates.

Each shipped Help Assistant is a *template*: a code-defined blueprint an
admin installs into their tenant from the admin UI (Add → <template>).
Installing a template creates the underlying assistant + role; the template
itself carries only lightweight identity (name, description) and the fixed
Help-Assistant invariants (logging/insights off, retention).

Instructions are intentionally NOT part of a template. A freshly added
helper starts blank; the admin pastes the canonical instructions (maintained
in the Eneo community) on the helper's settings page. This is why there is no
``prompt_text`` here, and why nothing is preseeded — the helper only exists
once an admin installs it.

Adding a new Help Assistant kind:
  1. extend ``HelperKind`` (``intric.help_assistants.domain.helper_kind``), and
  2. register a ``HelperAssistantTemplate`` for it below.

Each kind also owns its own UI integration ("hook") on the frontend — the
Prompt Guide surfaces a button on every assistant's settings page; another
kind might surface on a different admin page. This registry stays agnostic
about where each kind hooks in.
"""

from dataclasses import dataclass

from intric.help_assistants.domain.helper_kind import HelperKind

__all__ = [
    "PROMPT_GUIDE_TEMPLATE",
    "TEMPLATES_BY_KIND",
    "HelperAssistantTemplate",
    "HelperKind",
    "get_template",
    "list_templates",
]


@dataclass(frozen=True)
class HelperAssistantTemplate:
    """Frozen blueprint for an installable Help Assistant.

    Carries identity (``name`` / ``description``) and the fixed
    Help-Assistant invariants applied at install time. Deliberately holds no
    instruction text — a newly installed helper starts blank.
    """

    name: str
    description: str
    logging_enabled: bool = False
    insight_enabled: bool = False
    data_retention_days: int | None = 30


PROMPT_GUIDE_TEMPLATE = HelperAssistantTemplate(
    name="Prompt Guide",
    description=(
        "Helps an editor iterate on the system prompt of the assistant they "
        "are currently editing. Runs a short structured interview and "
        "produces a final, ready-to-use prompt at the end."
    ),
)


TEMPLATES_BY_KIND: dict[HelperKind, HelperAssistantTemplate] = {
    HelperKind.PROMPT_GUIDE: PROMPT_GUIDE_TEMPLATE,
}


def get_template(kind: HelperKind) -> HelperAssistantTemplate:
    """Return the shipped template for ``kind``.

    Raises ``KeyError`` if ``kind`` is not registered.
    """

    return TEMPLATES_BY_KIND[kind]


def list_templates() -> list[tuple[HelperKind, HelperAssistantTemplate]]:
    """All registered templates, in registry order."""

    return list(TEMPLATES_BY_KIND.items())
