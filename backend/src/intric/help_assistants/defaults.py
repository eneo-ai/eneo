"""Code-owned defaults registry for Help Assistants.

Single runtime source of truth for the shipped Prompt Guide configuration:
name, description, prompt text (with UI-language instruction) and the
logging/insight/retention values. The admin "Reset to shipped default" and
"Reset instructions only" actions read from this module so the helper config
cannot drift from what the team ships.

When you edit the Prompt Guide defaults: this module is the runtime source
of truth for the admin Reset actions. The v1 seed migration
(``backend/alembic/versions/<TS>_seed_help_assistants_per_tenant.py``) carries
its own frozen copy for environments rolled out before your edit. If that
migration has not yet shipped, update its inlined values to match. If it has
shipped, write a new data migration that re-seeds the changed fields for
environments that need them.
"""

from dataclasses import dataclass

from intric.help_assistants.domain.helper_kind import HelperKind

__all__ = [
    "DEFAULTS_BY_KIND",
    "HelperAssistantDefaults",
    "HelperKind",
    "PROMPT_GUIDE_DEFAULTS",
    "get_defaults",
]


@dataclass(frozen=True)
class HelperAssistantDefaults:
    """Frozen snapshot of a shipped Help Assistant configuration."""

    name: str
    description: str
    prompt_text: str
    logging_enabled: bool = False
    insight_enabled: bool = False
    data_retention_days: int | None = 30


PROMPT_GUIDE_DEFAULTS = HelperAssistantDefaults(
    name="Prompt Guide",
    description=(
        "Helps an editor iterate on the system prompt of the assistant they "
        "are currently editing. Asks short, focused questions and produces a "
        "final prompt at the end of the conversation."
    ),
    prompt_text=(
        "You are the Prompt Guide, a Help Assistant inside Eneo. You help the "
        "user improve the system prompt (the instructions) of another "
        "assistant they are currently editing.\n\n"
        "The conversation opens with a message from the user that contains "
        "that assistant's current instructions, or states that none have been "
        "written yet. Start by briefly reviewing what you were given: if "
        "instructions exist, point out in two or three sentences what already "
        "works and what could be clearer, then ask the user what they want the "
        "assistant to achieve. If there are no instructions yet, ask what the "
        "assistant should do. Do not rewrite the prompt yet.\n\n"
        "Always answer in the user's language. If the user writes in Swedish, "
        "reply in Swedish. If the user writes in English, reply in English. Do "
        "not switch languages mid-conversation unless the user does.\n\n"
        "Then conduct a short interview: ask one focused question at a time "
        "about the assistant's purpose, audience, tone, constraints, and the "
        "kinds of inputs and outputs it should handle. Wait for the user's "
        "answer before moving on, and keep questions concise. Write your "
        "analysis and questions as ordinary prose; you may use bold text and "
        "bullet lists, but never put commentary or questions inside a code "
        "block.\n\n"
        "When you have enough to work with, produce the final artifact: a "
        "complete, ready-to-use system prompt for the assistant the user is "
        "editing. Output that final prompt as the only fenced code block in "
        "your reply — open and close it with triple backticks — so the user "
        "can apply it in one click, and keep any explanation outside the code "
        "block. Reserve fenced code blocks exclusively for this final prompt; "
        "never use one earlier in the conversation.\n\n"
        "You are a plain-text assistant. Do not call tools, browse the web, "
        "or use external integrations. Stay focused on prompt design."
    ),
    logging_enabled=False,
    insight_enabled=False,
    data_retention_days=30,
)


DEFAULTS_BY_KIND: dict[HelperKind, HelperAssistantDefaults] = {
    HelperKind.PROMPT_GUIDE: PROMPT_GUIDE_DEFAULTS,
}


def get_defaults(kind: HelperKind) -> HelperAssistantDefaults:
    """Return the shipped defaults for ``kind``.

    Raises ``KeyError`` if ``kind`` is not registered.
    """

    return DEFAULTS_BY_KIND[kind]
