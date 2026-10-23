"""Text rendering of source document properties.

Shared by the embedding path (so a query can match a document on its
properties, not only its body) and the prompt context (so the model can tell
the reader what kind of document a source is). Both must agree on the wording:
what retrieval matched on should be what the model and the person see.
"""

from collections.abc import Callable, Sequence

from eneo.info_blobs.info_blob import SourceMetadataEntry

# Multi-value properties are joined with this inside one line.
_LIST_SEPARATOR = ", "


def _display_value(entry: SourceMetadataEntry) -> str:
    value = entry.value
    if isinstance(value, list):
        return _LIST_SEPARATOR.join(v for v in value if v)
    if entry.kind == "date":
        # Graph returns ISO 8601 timestamps; the day is what people search for.
        return value[:10] if len(value) >= 10 and value[4:5] == "-" else value
    if entry.kind == "boolean":
        return "yes" if value.lower() == "true" else "no"
    return value


def format_source_metadata_lines(entries: Sequence[SourceMetadataEntry]) -> list[str]:
    """``Label: value`` lines, in the source's own column order."""
    lines: list[str] = []
    for entry in entries:
        value = _display_value(entry)
        if not value:
            continue
        lines.append(f"{entry.label}: {value}")
    return lines


def build_source_header(
    *,
    title: str | None,
    entries: Sequence[SourceMetadataEntry],
    token_budget: int,
    count_tokens: Callable[[str], int],
) -> str:
    """The header prepended to each chunk before embedding.

    Returns an empty string when there are no properties: documents without
    source metadata keep their embeddings byte-for-byte unchanged. Lines are
    dropped from the end until the header fits ``token_budget`` so a library
    with many wide columns cannot crowd out the chunk's own text.
    """
    lines = format_source_metadata_lines(entries)
    if not lines:
        return ""
    if title and title.strip():
        lines.insert(0, title.strip())

    while lines:
        header = "\n".join(lines) + "\n\n"
        if count_tokens(header) <= token_budget:
            return header
        lines.pop()
    return ""
