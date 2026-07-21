from __future__ import annotations

from eneo.flows.flow_error_taxonomy import (
    FLOW_ERROR_CATEGORY_ORDER,
    FLOW_ERROR_TAXONOMY,
    validate_flow_error_taxonomy,
)
from eneo.flows.infrastructure.flow_docs_mermaid import (
    render_flow_docs_mermaid_block,
)
from eneo.flows.infrastructure.flow_docs_related_cards import (
    FLOW_DOCS_RELATED_NEXTRA_CARDS_IMPORT,
    FlowDocsRelatedNextraCard,
    render_flow_docs_related_nextra_cards,
)


def render_flow_error_taxonomy_docs_page() -> str:
    validate_flow_error_taxonomy()
    parts = [
        FLOW_DOCS_RELATED_NEXTRA_CARDS_IMPORT,
        "",
        "# When things fail",
        "",
        "Use this page when a Flow error reaches an API consumer or end user. It maps each code to the handling phase, source surface, and recovery action.",
        "",
        "## Error delivery map",
        "",
        _render_delivery_diagram(),
        "",
        "## How to use this page",
        "",
        "- `API error response` means the request failed before or during the HTTP operation.",
        "- `Run error payload` means the run reached a terminal state with a structured `run.error.code`.",
        "- `API response and run error payload` means the same code may be seen either synchronously or after runtime terminalization.",
        "- API consumers should poll the run, branch on `run.error.code`, and localize `flow_error_<code>`.",
        "- `run.dispatch_last_error.retryable` means internal recovery may retry the current dispatch epoch before terminalization.",
        "- `run.error.retryable` means a consumer may safely submit a new logical run after terminalization. Neither retryable field starts work automatically.",
        "- For create-run backpressure, branch on HTTP `429` plus `flow_run_concurrency_limit_reached`, honor `Retry-After`, and do not branch on legacy numeric code `9007`.",
        "- Use `/guides/flows-api-guide` for the polling, review, rerun, evidence, and artifact API paths.",
        "- Run `make docs:regen` from the repository root after changing Flow error codes, metadata, or localization.",
        "- End users should see the user action, not backend internals or invariant names.",
        "",
        "## Failure triage",
        "",
        _render_failure_triage_table(),
        "",
        "## Failure taxonomy",
        "",
        *_render_category_sections(),
        "## Source guards",
        "",
        _render_source_guard_table(),
        "",
        "## Related",
        "",
        render_flow_docs_related_nextra_cards(
            (
                FlowDocsRelatedNextraCard(
                    "The run lifecycle",
                    "/docs/flows-for-developers/run-lifecycle",
                ),
                FlowDocsRelatedNextraCard(
                    "Key decisions",
                    "/docs/flows-for-developers/key-decisions",
                ),
            )
        ),
        "",
    ]
    return "\n".join(parts)


def _render_delivery_diagram() -> str:
    return render_flow_docs_mermaid_block(
        "flowchart LR",
        '  backend["Flow API and runtime"] --> code["FlowApiErrorCode"]',
        '  code --> api["Flow API error response"]',
        '  code --> run["Run error payload"]',
        '  api --> sdk["SDK"]',
        "  run --> sdk",
        '  sdk --> frontend["Frontend messages"]',
        '  code --> docs["When things fail taxonomy"]',
        '  docs --> action["Developer action"]',
        '  frontend --> user["End-user recovery text"]',
    )


def _render_failure_triage_table() -> str:
    return _render_markdown_table(
        (
            "Symptom",
            "Start with category",
            "Public surface",
            "Next check",
        ),
        [
            (
                "Request rejected before the run starts",
                "Run input or Flow access",
                "API error response",
                "Validate request shape, tenant access, idempotency, and published version.",
            ),
            (
                "Step failed during execution",
                "Step runtime or Typed input/output",
                "Run error payload",
                "Open the failed step, handler diagnostics, and typed IO contract.",
            ),
            (
                "Run stopped after queueing",
                "Run lifecycle",
                "Run error payload",
                "Check worker dispatch, timeout, stalled-run recovery, and terminalization logs.",
            ),
            (
                "Review or rerun action failed",
                "Review checkpoint or Rerun",
                "API error response",
                "Check revision, idempotency key, checkpoint state, and rerun fingerprint.",
            ),
            (
                "Evidence or artifact cannot be read",
                "Evidence and artifacts",
                "API error response",
                "Check permission, retention, audit reason, and listed artifact ids.",
            ),
        ],
    )


def _render_category_sections() -> list[str]:
    sections: list[str] = []
    for category in FLOW_ERROR_CATEGORY_ORDER:
        rows = [
            (
                f"`{code.value}`",
                entry.surfaced_through,
                entry.cause,
                entry.consumer_action,
                entry.user_action,
            )
            for code, entry in FLOW_ERROR_TAXONOMY.items()
            if entry.category == category
        ]
        if not rows:
            continue
        sections.extend(
            [
                f"### {category}",
                "",
                _render_details(
                    f"{len(rows)} error codes",
                    _render_markdown_table(
                        (
                            "Code",
                            "Surface",
                            "Cause",
                            "Consumer action",
                            "User action",
                        ),
                        rows,
                    ),
                ),
                "",
            ]
        )
    return sections


def _render_source_guard_table() -> str:
    return _render_markdown_table(
        (
            "Source",
            "Guard",
        ),
        (
            (
                "`backend/src/eneo/flows/flow_api_error_code.py`",
                "Every `FlowApiErrorCode` value must have one taxonomy entry.",
            ),
            (
                "`backend/src/eneo/flows/flow_error_taxonomy.py`",
                "Every taxonomy entry must stay short, categorized, and typed.",
            ),
            (
                "`frontend/apps/web/messages/en.json`",
                "Every code must have a `flow_error_*` English localization key.",
            ),
            (
                "`frontend/apps/docs-site/src/content/docs/flows-for-developers/when-things-fail.mdx`",
                "The committed page must equal regenerated output.",
            ),
        ),
    )


def _render_details(summary: str, body: str) -> str:
    return "\n".join(
        (
            "<details>",
            f"<summary>{summary}</summary>",
            "",
            body,
            "",
            "</details>",
        )
    )


def _render_markdown_table(
    headers: tuple[str, ...],
    rows: tuple[tuple[str, ...], ...] | list[tuple[str, ...]],
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
    return value.replace("|", "\\|").replace("\n", " ")
