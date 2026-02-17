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
    "You are an expert in data analysis. Below, enclosed by triple quotation marks, "
    "are the questions that have been asked to an AI assistant in the"
    "last {days} days. Use these to answer questions."
)

SET_TITLE_OF_CONVERSATION_PROMPT = """
You are an expert in summarizing conversations.

Given a conversation, please summarize the conversation in a title.

The title should be a single sentence that captures the essence of the conversation.

The title should be in the language of the conversation.

The title should be no more than 10 words.
"""
