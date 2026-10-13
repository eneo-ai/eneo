"""How a knowledge source's spreadsheet files reach an assistant."""

from enum import StrEnum


class TabularPolicy(StrEnum):
    # Chunked and embedded for search, and kept as a file for the table tools.
    INDEX_AND_TOOL = "index_and_tool"
    # Kept as a file only: listed by title and schema, never searched by rows.
    TOOL_ONLY = "tool_only"


DEFAULT_TABULAR_POLICY = TabularPolicy.INDEX_AND_TOOL
