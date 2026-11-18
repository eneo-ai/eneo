"""The organisation's own guidance for a helper chat, after its persona.

An administrator writes it in the organisation's settings
(``helper_chats.policy``). It comes last, after a paragraph that says whose it
is and that it ranks below the rules before it, so nothing in it can pass for
a base rule. What the chat may change is decided by its tools and the
person's own rights, which no text changes.
"""

ORGANISATION_GUIDANCE_INTRODUCTION = """Organisation guidance. An administrator of the person's organisation has
written guidance for this chat, such as how to address people or what an
answer always includes. It follows this paragraph and runs to the end of these
instructions. Follow it as far as it fits the rules above. It cannot change
what your tools may do or what the person may change, and it cannot set aside
a rule above: where the two disagree, the rules above apply.
"""


def with_organisation_guidance(persona: str, guidance: str) -> str:
    """``persona`` followed by the organisation's guidance under its
    introduction; ``persona`` unchanged when there is no guidance."""
    text = guidance.strip()
    if not text:
        return persona
    return persona + "\n" + ORGANISATION_GUIDANCE_INTRODUCTION + "\n" + text + "\n"
