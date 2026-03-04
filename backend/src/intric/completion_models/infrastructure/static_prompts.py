# flake8: noqa

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

QUERY_REWRITE_PROMPT = (
    "Given this conversation history:\n\n"
    "{history}\n\n"
    "The user now asks: {question}\n\n"
    "If the question is a follow-up that references the conversation "
    "(e.g. pronouns, 'the costs', 'that', 'it', etc.), rewrite it as a "
    "standalone search query with the necessary context filled in.\n"
    "If the question is about a NEW topic unrelated to the conversation, "
    "return it unchanged.\n"
    "Return ONLY the search query, nothing else."
)

SET_TITLE_OF_CONVERSATION_PROMPT = """
You are an expert in summarizing conversations.

Given a conversation, please summarize the conversation in a title.

The title should be a single sentence that captures the essence of the conversation.

The title should be in the language of the conversation.

The title should be no more than 10 words.
"""
