# flake8: noqa

# Header for the canonical MCP resource context that the adapter appends to a
# tool result before forwarding it to the LLM. The content under this header is
# intentionally structured around generic MCP resource fields, not UI wording.
MCP_TOOL_REFERENCES_CONTEXT_HEADER = "MCP referenced resources:"

# Inline instruction appended to the MCP resource context. Lives next to the
# data so the model gets the citation rule whenever a tool returns resources —
# without requiring the system-level SHOW_REFERENCES_PROMPT (that one only fires
# when knowledge/web_search results are present, leaving MCP-only flows untaught).
MCP_TOOL_REFERENCES_INSTRUCTION = (
    "When using information from an MCP referenced resource above, cite it with "
    "the matching inline tag immediately after the relevant text: "
    '<inref id="<source_id>"/>. Use the 8-character source_id value from the '
    "resource object."
)

SHOW_REFERENCES_PROMPT = """Use the provided sources delimited by triple quotes to answer questions.
Only use the sources to answer questions. You MUST reference every source you use by adding an inline XML self-closing tag immediately after the information: <inref id="<source_id>"/>

Rules:
- Every claim, fact, or piece of information taken from a source MUST be followed by its reference tag.
- Use the 8-character source_id from the source metadata. Example: if source_id is a5477f85, write <inref id="a5477f85"/> right after the relevant sentence or paragraph.
- If information comes from multiple sources, include multiple tags: <inref id="a5477f85"/><inref id="b3291cc0"/>
- If the user asks about the sources, respond with the source_title, never the source_id.
- If you cannot find the information in any of the sources, politely respond that the answer cannot be found.
- Never omit references. A response that uses source information without inline reference tags is incorrect."""

HALLUCINATION_GUARD = (
    "Use the provided articles delimited by triple quotes to"
    " answer questions. If the answer cannot be found in the articles, respond that"
    " the answer could not be found."
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
