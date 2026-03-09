# flake8: noqa

_NOT_FOUND_DEFAULT = "politely respond that the answer cannot be found."
_NOT_FOUND_WITH_TOOLS = "use your available tools to find the answer before responding that it cannot be found."

SHOW_REFERENCES_PROMPT = """Use the provided sources delimited by triple quotes to answer questions.
Only use the sources to answer questions. You MUST reference every source you use by adding an inline XML self-closing tag immediately after the information: <inref id="<source_id>"/>

Rules:
- Every claim, fact, or piece of information taken from a source MUST be followed by its reference tag.
- Use the 8-character source_id from the source metadata. Example: if source_id is a5477f85, write <inref id="a5477f85"/> right after the relevant sentence or paragraph.
- If information comes from multiple sources, include multiple tags: <inref id="a5477f85"/><inref id="b3291cc0"/>
- If the user asks about the sources, respond with the source_title, never the source_id.
- If you cannot find the information in any of the sources, {not_found}
- Never omit references. A response that uses source information without inline reference tags is incorrect.
- Only add reference tags for information that actually comes from the provided sources. Do NOT add reference tags to information obtained from tool calls."""


def get_show_references_prompt(has_tools: bool = False) -> str:
    return SHOW_REFERENCES_PROMPT.format(
        not_found=_NOT_FOUND_WITH_TOOLS if has_tools else _NOT_FOUND_DEFAULT
    )


_HALLUCINATION_GUARD_DEFAULT = "respond that the answer could not be found."
_HALLUCINATION_GUARD_WITH_TOOLS = "use your available tools to find the answer before responding that it could not be found."

TOOL_USAGE_GUARD = "Avoid making duplicate or near-identical tool calls."

HALLUCINATION_GUARD = (
    "Use the provided articles delimited by triple quotes to"
    " answer questions. If the answer cannot be found in the articles, {not_found}"
)


def get_hallucination_guard(has_tools: bool = False) -> str:
    return HALLUCINATION_GUARD.format(
        not_found=_HALLUCINATION_GUARD_WITH_TOOLS if has_tools else _HALLUCINATION_GUARD_DEFAULT
    )

TRANSCRIPTION_PROMPT = """In the input, marked with \"transcription: \"\"<text>\"\"\" is transcribed audio. Please provide a detailed summary of the transcription(s) in the language of the transcribed text."""

ANALYSIS_PROMPT = (
    "You are an expert analyst reviewing user questions asked to an AI assistant "
    "over the last {days} days.\n\n"
    "The questions are enclosed in triple quotation marks below. "
    "Repeated questions are shown once with a frequency count (e.g. [x5] means 5 occurrences).\n\n"
    "Guidelines:\n"
    "- Answer in the same language the user asks in.\n"
    "- Cite specific question examples when relevant.\n"
    "- If the data is insufficient to answer confidently, say so.\n"
    "- Be concise and factual."
)

SET_TITLE_OF_CONVERSATION_PROMPT = """
You are an expert in summarizing conversations.

Given a conversation, please summarize the conversation in a title.

The title should be a single sentence that captures the essence of the conversation.

The title should be in the language of the conversation.

The title should be no more than 10 words.
"""
