from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from eneo.flows.flow_error_taxonomy import (
    FLOW_ERROR_CATEGORY_ORDER,
    FLOW_ERROR_TAXONOMY,
    validate_flow_error_taxonomy,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FLOW_CONSUMER_ERROR_REFERENCE_OUTPUT_PATH = (
    REPO_ROOT
    / "frontend"
    / "apps"
    / "docs-site"
    / "src"
    / "content"
    / "guides"
    / "flows"
    / "reference"
    / "errors.mdx"
)


@dataclass(frozen=True, slots=True)
class FlowConsumerErrorCatalogRow:
    category: str
    code: str
    handling_phase: str
    consumer_action: str


def flow_consumer_error_catalog_rows() -> tuple[FlowConsumerErrorCatalogRow, ...]:
    validate_flow_error_taxonomy()
    category_order = {
        category: index for index, category in enumerate(FLOW_ERROR_CATEGORY_ORDER)
    }
    ordered_entries = sorted(
        FLOW_ERROR_TAXONOMY.items(),
        key=lambda item: (category_order[item[1].category], item[0].value),
    )
    return tuple(
        FlowConsumerErrorCatalogRow(
            category=entry.category,
            code=code.value,
            handling_phase=entry.handling_phase,
            consumer_action=entry.consumer_action,
        )
        for code, entry in ordered_entries
    )


def render_flow_consumer_error_catalog_table() -> str:
    rows = tuple(
        (
            row.category,
            f"`{row.code}`",
            row.handling_phase,
            row.consumer_action,
        )
        for row in flow_consumer_error_catalog_rows()
    )
    return _render_markdown_table(
        ("Category", "Code", "Handling phase", "Consumer action"),
        rows,
    )


def render_flow_consumer_error_reference_page() -> str:
    return "\n".join(
        (
            "# Flow error reference",
            "",
            "This page is for teams turning Eneo Flows error codes into clear recovery paths, and it shows which failures belong to request handling and which belong to run execution.",
            "",
            "Use this as the canonical consumer reference for `FlowApiErrorCode`. Task guides link here instead of repeating code lists.",
            "",
            "## The error envelope",
            "",
            "Every `4xx` and `5xx` response from the Flow runtime API has the same JSON body:",
            "",
            "```json",
            "{",
            '  "message": "Flow must be published before creating runs.",',
            '  "code": "flow_not_published",',
            '  "eneo_error_code": 9007,',
            '  "context": { "step_ids": ["00000000-0000-0000-0000-000000000101"] },',
            '  "request_id": "7796bdacde5f9f7536cdbf3a7e50b5c4"',
            "}",
            "```",
            "",
            "- **`code` is the contract.** It is a stable string, present on every error. Branch your client on this field and nothing else.",
            "- **`message` is for humans.** It is not stable and must not drive control flow.",
            "- **`context` carries recovery hints** for some codes, such as the `step_ids` that are missing a required upload, or `auth_layer` on an authentication or scope rejection.",
            "- **`request_id` is for support.** Quote it, together with the run id, when reporting a problem.",
            "- **`error_id` appears on unexpected server errors** and points support at the originating exception log. Log it whenever it is present.",
            "- **`eneo_error_code` is a legacy numeric category, not an identifier.** It is derived from the exception class rather than from `code`, so it is many-to-one: most of the catalog below shares a single value, while a few codes carry a different one. It cannot distinguish two failures and must not drive control flow.",
            "",
            "Fields that carry no value are omitted rather than sent as `null`, so treat every field except `message` and `code` as optional.",
            "",
            "## Codes that are not `FlowApiErrorCode`",
            "",
            "The catalog below covers Flow-specific failures. A Flow client will also meet these platform-level codes, most of them on the authentication and upload paths, and they are not in the `FlowApiErrorCode` enum:",
            "",
            _render_markdown_table(
                ("HTTP", "`code`", "When", "Consumer action"),
                (
                    (
                        "`401`",
                        "`authentication_error`",
                        "No credential was sent at all",
                        "Send `X-API-Key` or `Authorization: Bearer`",
                    ),
                    (
                        "`401`",
                        "`invalid_api_key`",
                        "The API key does not exist, is revoked, or is malformed. `context.auth_layer` is `identity`",
                        "Do not retry with the same key",
                    ),
                    (
                        "`403`",
                        "`insufficient_scope`",
                        "The key authenticated but its scope or permissions do not cover the request. `context.auth_layer` is `api_key_scope`. Scope is evaluated before the resource is resolved, so a flow in another space returns this rather than `404`",
                        "Fix the key's scope or permissions",
                    ),
                    (
                        "`403`",
                        "`insufficient_resource_permission`",
                        "The API key authenticated and is in scope, but its `resource_permissions` do not grant the needed level for this resource type. `context` reports `resource_type`, `required_level`, and `granted_level`",
                        "Reissue the key with the level `context.required_level` names, for example `flows = write` for run creation and review decisions",
                    ),
                    (
                        "`403`",
                        "`insufficient_space_permission`",
                        "The principal is in the space but lacks the required role. `context.auth_layer` is `space_membership`",
                        "Grant the role, or call the published runtime endpoints instead",
                    ),
                    (
                        "`404`",
                        "`not_found`",
                        "The flow, run, checkpoint, or file is not visible to this principal in this tenant",
                        "Do not retry. Refetch the list the id came from",
                    ),
                    (
                        "`413`",
                        "`file_too_large`",
                        "The uploaded file exceeds the step's `max_file_size_bytes`. The check happens after the body has been received, so the transfer is not saved",
                        "Read the effective limit from the run contract and reject the file client-side before uploading",
                    ),
                    (
                        "`415`",
                        "`unsupported_media_type`",
                        "The uploaded part's declared or sniffed `Content-Type` is not in the step's `accepted_mimetypes`. `context` reports `received_type` and `detected_type`",
                        "Set the part's `Content-Type` from the run contract. The message lists every accepted type",
                    ),
                    (
                        "`422`",
                        "`request_validation_error`",
                        "The request body or multipart form did not match the schema, for example a file part sent under a name other than `upload_file`. `details.errors` names each offending field",
                        "Fix the request shape. This is a client bug, not a runtime state",
                    ),
                ),
            ),
            "",
            "## How to handle codes",
            "",
            "- Handle `Request path` codes from the failed API response before you create, edit, resume, or rerun a run.",
            "- Handle `Run execution` codes from `run.error.code` while polling or rendering a terminal failed run.",
            "- Handle `Request path or run execution` codes in both places; the same logical failure can surface synchronously or after worker execution.",
            "- Unknown codes should degrade gracefully: show a generic Flow failure message, keep the raw code for support, and avoid automatic destructive retries.",
            "- Do not automatically retry an LLM request timeout or ambiguous step execution failure: provider work may or may not have started, and a rerun can duplicate provider work and spend.",
            "- A failed `per_source` or `per_item` step has no partial continuation: rerunning the step repeats every source or item provider call, including calls that may already have completed.",
            "",
            "## Catalog",
            "",
            render_flow_consumer_error_catalog_table(),
            "",
            "Next: [Flow Runtime API Reference](/guides/flows-api-guide)",
            "",
        )
    )


def write_flow_consumer_error_reference_page() -> None:
    FLOW_CONSUMER_ERROR_REFERENCE_OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    FLOW_CONSUMER_ERROR_REFERENCE_OUTPUT_PATH.write_text(
        render_flow_consumer_error_reference_page(),
        encoding="utf-8",
    )


def _render_markdown_table(
    headers: tuple[str, ...],
    rows: Sequence[tuple[str, ...]],
) -> str:
    escaped_rows = [tuple(_escape_cell(cell) for cell in row) for row in rows]
    widths = [
        max(len(row[column_index]) for row in (headers, *escaped_rows))
        for column_index in range(len(headers))
    ]

    def render_row(cells: tuple[str, ...]) -> str:
        padded_cells = [
            cell.ljust(widths[column_index]) for column_index, cell in enumerate(cells)
        ]
        return f"| {' | '.join(padded_cells)} |"

    separator = tuple("-" * max(3, width) for width in widths)
    return "\n".join(
        [render_row(headers), render_row(separator), *map(render_row, escaped_rows)]
    )


def _escape_cell(value: str) -> str:
    return value.replace("|", "\\|")
