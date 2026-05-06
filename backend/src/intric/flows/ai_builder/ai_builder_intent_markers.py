from __future__ import annotations

INPUT_ROLE_MARKERS: tuple[str, ...] = (
    "ladda upp",
    "laddar upp",
    "upload",
    "skicka in",
    "send in",
    "ta emot",
    "tar emot",
    "receive",
    "attach",
    "bifoga",
    "bifogade",
    "uppladdad",
    "uppladdat",
    "uppladdade",
    "uploaded",
    "vid körning",
    "runtime input",
)

OUTPUT_ROLE_MARKERS: tuple[str, ...] = (
    "generera",
    "genererar",
    "generate",
    "returnera",
    "returnerar",
    "return",
    "leverera",
    "levererar",
    "deliver",
    "skapa",
    "skapar",
    "create",
    "producera",
    "producerar",
    "produce",
    "få tillbaka",
    "få ut",
    "få en",
    "få ett",
    "get a",
    "get an",
    "get back",
    "skriv",
    "skriver",
    "write",
    "slutresultatet",
    "final output",
)

TERMINAL_OUTPUT_POSITION_MARKERS: tuple[str, ...] = (
    "i slutet",
    "på slutet",
    "till sist",
    "slutligen",
    "som slutprodukt",
    "som leverans",
    "i slutändan",
    "finalt",
    "at the end",
    "in the end",
    "lastly",
    "finally",
    "as final output",
    "as the final output",
    "as deliverable",
)

# These markers only decide clause role near terminal-position wording. Detailed
# DOCX/PDF mode classification remains owned by ai_builder_keywords.py.
TERMINAL_OUTPUT_ARTIFACT_MARKERS: tuple[str, ...] = (
    "docx",
    "word",
    "pdf",
    "json",
)

TERMINAL_OUTPUT_PRECEDING_ARTIFACT_LEAD_IN_MARKERS: tuple[str, ...] = (
    "jag vill ha",
    "vill ha",
    "jag behöver",
    "behöver",
    "ska få",
    "få ut",
    "want",
    "i want",
    "need",
    "should return",
    "should produce",
)

TERMINAL_OUTPUT_ARTIFACT_FILLER_TOKENS: tuple[str, ...] = (
    "fil",
    "file",
    "dokument",
    "document",
    "rapport",
    "report",
    "som",
    "as",
)

REPLACEMENT_PHRASES: tuple[str, ...] = (
    "i stället för",
    "istället för",
    "instead of",
)
