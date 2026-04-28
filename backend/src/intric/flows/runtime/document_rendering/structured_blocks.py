from __future__ import annotations

from typing import Any, cast

from intric.flows.runtime.document_rendering.blocks import (
    EMPTY_VALUE_PLACEHOLDER,
    DocumentBlock,
)


def structured_data_to_blocks(
    data: dict[str, Any] | list[Any],
    *,
    schema: dict[str, Any] | None,
) -> list[DocumentBlock]:
    blocks: list[DocumentBlock] = []
    schema_title = schema.get("title") if isinstance(schema, dict) else None
    if isinstance(schema_title, str) and schema_title.strip():
        blocks.append(
            DocumentBlock(
                kind="heading",
                text=_single_line_text(schema_title),
                level=1,
            )
        )
        blocks.append(DocumentBlock(kind="empty"))
    blocks.extend(
        _blocks_for_value(
            value=data,
            label=None,
            schema=schema if isinstance(schema, dict) else None,
            level=2 if blocks else 1,
        )
    )
    return _trim_trailing_empty_blocks(blocks)


def _blocks_for_value(
    *,
    value: Any,
    label: str | None,
    schema: dict[str, Any] | None,
    level: int,
) -> list[DocumentBlock]:
    if isinstance(value, dict):
        return _blocks_for_object(
            value=cast(dict[str, Any], value),
            label=label,
            schema=schema,
            level=level,
        )
    if isinstance(value, list):
        return _blocks_for_array(
            value=cast(list[Any], value),
            label=label,
            schema=schema,
            level=level,
        )
    rendered_value = _scalar_text(value)
    if label is None:
        return [DocumentBlock(kind="paragraph", text=rendered_value)]
    return [
        DocumentBlock(kind="paragraph", text=f"{label}: {rendered_value}"),
        DocumentBlock(kind="empty"),
    ]


def _blocks_for_object(
    *,
    value: dict[str, Any],
    label: str | None,
    schema: dict[str, Any] | None,
    level: int,
) -> list[DocumentBlock]:
    blocks: list[DocumentBlock] = []
    if label:
        blocks.append(DocumentBlock(kind="heading", text=label, level=min(level, 4)))
        blocks.append(DocumentBlock(kind="empty"))
        level += 1

    properties = _as_str_dict(schema.get("properties") if schema is not None else None)
    ordered_keys = _ordered_object_keys(value, properties)
    if not ordered_keys:
        blocks.append(DocumentBlock(kind="paragraph", text=EMPTY_VALUE_PLACEHOLDER))
        blocks.append(DocumentBlock(kind="empty"))
        return blocks

    for key in ordered_keys:
        field_schema = _as_str_dict(properties.get(key) if properties else None)
        field_label = _schema_label(key, field_schema)
        blocks.extend(
            _blocks_for_value(
                value=value.get(key),
                label=field_label,
                schema=field_schema,
                level=level,
            )
        )
    return blocks


def _blocks_for_array(
    *,
    value: list[Any],
    label: str | None,
    schema: dict[str, Any] | None,
    level: int,
) -> list[DocumentBlock]:
    blocks: list[DocumentBlock] = []
    if not value:
        if label:
            blocks.append(
                DocumentBlock(kind="heading", text=label, level=min(level, 4))
            )
            blocks.append(DocumentBlock(kind="empty"))
        blocks.append(DocumentBlock(kind="paragraph", text=EMPTY_VALUE_PLACEHOLDER))
        blocks.append(DocumentBlock(kind="empty"))
        return blocks

    if label:
        blocks.append(DocumentBlock(kind="heading", text=label, level=min(level, 4)))
        blocks.append(DocumentBlock(kind="empty"))

    if all(_is_scalar(item) for item in value):
        blocks.append(
            DocumentBlock(
                kind="bullet_list",
                items=tuple(_scalar_text(item) for item in value),
            )
        )
        blocks.append(DocumentBlock(kind="empty"))
        return blocks

    if _can_render_object_table(value):
        blocks.append(
            _table_block_for_objects(
                rows=cast(list[dict[str, Any]], value),
                schema=schema,
            )
        )
        blocks.append(DocumentBlock(kind="empty"))
        return blocks

    item_schema = _as_str_dict(schema.get("items") if schema is not None else None)
    for index, item in enumerate(value, start=1):
        blocks.extend(
            _blocks_for_value(
                value=item,
                label=f"Item {index}",
                schema=item_schema,
                level=level + 1,
            )
        )
    return blocks


def _ordered_object_keys(
    value: dict[str, Any], properties: dict[str, Any] | None
) -> list[str]:
    ordered: list[str] = []
    if properties is not None:
        ordered.extend(key for key in properties if key in value)
    ordered.extend(key for key in value if key not in ordered)
    return ordered


def _schema_label(key: str, schema: dict[str, Any] | None) -> str:
    title = schema.get("title") if isinstance(schema, dict) else None
    if isinstance(title, str) and title.strip():
        return _single_line_text(title)
    return _single_line_text(key.replace("_", " ").strip().capitalize() or key)


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _can_render_object_table(value: list[Any]) -> bool:
    for item in value:
        if not isinstance(item, dict):
            return False
        row = cast(dict[str, Any], item)
        if not all(_is_scalar(field) for field in row.values()):
            return False
    return True


def _table_block_for_objects(
    *, rows: list[dict[str, Any]], schema: dict[str, Any] | None
) -> DocumentBlock:
    item_schema = _as_str_dict(schema.get("items") if schema is not None else None)
    item_properties = _as_str_dict(
        item_schema.get("properties") if item_schema is not None else None
    )
    columns = _ordered_table_columns(rows=rows, item_properties=item_properties)
    if not columns:
        return DocumentBlock(kind="paragraph", text=EMPTY_VALUE_PLACEHOLDER)

    header = tuple(
        _schema_label(
            column,
            _as_str_dict(item_properties.get(column) if item_properties else None),
        )
        for column in columns
    )
    body = tuple(
        tuple(_scalar_text(row.get(column)) for column in columns) for row in rows
    )
    return DocumentBlock(kind="table", rows=(header, *body))


def _ordered_table_columns(
    *,
    rows: list[dict[str, Any]],
    item_properties: dict[str, Any] | None,
) -> list[str]:
    columns: list[str] = []
    if item_properties is not None:
        columns.extend(
            key
            for key in item_properties
            if any(key in row for row in rows) and key not in columns
        )
    for row in rows:
        columns.extend(key for key in row if key not in columns)
    return columns


def _scalar_text(value: Any) -> str:
    if value is None:
        return EMPTY_VALUE_PLACEHOLDER
    if isinstance(value, bool):
        return "true" if value else "false"
    return _plain_text(str(value)) or EMPTY_VALUE_PLACEHOLDER


def _plain_text(value: str) -> str:
    return value.replace("```", "'''").replace("\r\n", "\n").replace("\r", "\n").strip()


def _single_line_text(value: str) -> str:
    return (
        value.replace("```", "'''")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", " ")
        .strip()
    )


def _as_str_dict(value: object) -> dict[str, Any] | None:
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def _trim_trailing_empty_blocks(blocks: list[DocumentBlock]) -> list[DocumentBlock]:
    trimmed = list(blocks)
    while trimmed and trimmed[-1].kind == "empty":
        trimmed.pop()
    return trimmed
