from __future__ import annotations

import inspect
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from importlib import import_module
from pathlib import Path
from typing import cast
from uuid import UUID

import sqlalchemy as sa

from eneo.database.tables import flow_tables
from eneo.database.tables.flow_classification_retention_policy_table import (
    FlowClassificationRetentionPolicies,
)
from eneo.flows.infrastructure.flow_docs_mermaid import (
    render_flow_docs_mermaid_block,
)
from eneo.flows.infrastructure.flow_docs_related_cards import (
    FLOW_DOCS_RELATED_NEXTRA_CARDS_IMPORT,
    FlowDocsRelatedNextraCard,
    render_flow_docs_related_nextra_cards,
)
from eneo.flows.infrastructure.flow_jsonb_ownership import (
    FLOW_JSONB_COLUMN_OWNERS,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
FLOW_DEVELOPER_SCHEMA_DOCS_OUTPUT_PATH = (
    REPO_ROOT
    / "frontend"
    / "apps"
    / "docs-site"
    / "src"
    / "content"
    / "docs"
    / "flows-for-developers"
    / "data-schema.mdx"
)

_WRITER_MARKER = " Writer: "
_PURPOSE_MARKER = " Purpose: "
_TENANT_TABLE_NAME = "tenants"
_TENANT_COLUMN_NAME = "tenant_id"
_FLOW_TABLE_NAME = "flows"
_RUN_TABLE_NAME = "flow_runs"


class FlowSchemaAggregate(Enum):
    FLOW_DEFINITION = "Flow definition, versions, and authoring"
    RUN_EXECUTION = "Run execution, results, and files"
    REVIEW_AND_RERUN = "Review checkpoints and rerun lineage"
    RETENTION = "Retention and classification"
    DEFERRED_ADJACENT = "Deferred adjacent tables"


@dataclass(frozen=True, slots=True)
class FlowSchemaModelEntry:
    model: type[object]
    aggregate: FlowSchemaAggregate


FLOW_SCHEMA_MODEL_REGISTRY: tuple[FlowSchemaModelEntry, ...] = (
    FlowSchemaModelEntry(flow_tables.Flows, FlowSchemaAggregate.FLOW_DEFINITION),
    FlowSchemaModelEntry(flow_tables.FlowVersions, FlowSchemaAggregate.FLOW_DEFINITION),
    FlowSchemaModelEntry(flow_tables.FlowSteps, FlowSchemaAggregate.FLOW_DEFINITION),
    FlowSchemaModelEntry(
        flow_tables.FlowTemplateAssets, FlowSchemaAggregate.FLOW_DEFINITION
    ),
    FlowSchemaModelEntry(
        flow_tables.FlowResourceBindings, FlowSchemaAggregate.FLOW_DEFINITION
    ),
    FlowSchemaModelEntry(flow_tables.FlowRuns, FlowSchemaAggregate.RUN_EXECUTION),
    FlowSchemaModelEntry(
        flow_tables.FlowStepResults, FlowSchemaAggregate.RUN_EXECUTION
    ),
    FlowSchemaModelEntry(
        flow_tables.FlowStepAttempts, FlowSchemaAggregate.RUN_EXECUTION
    ),
    FlowSchemaModelEntry(
        flow_tables.FlowStepAttemptResolvedInputs,
        FlowSchemaAggregate.RUN_EXECUTION,
    ),
    FlowSchemaModelEntry(
        flow_tables.FlowProviderCalls, FlowSchemaAggregate.RUN_EXECUTION
    ),
    FlowSchemaModelEntry(
        flow_tables.FlowRuntimeUploadedFiles, FlowSchemaAggregate.RUN_EXECUTION
    ),
    FlowSchemaModelEntry(
        flow_tables.FlowRunStepInputFiles, FlowSchemaAggregate.RUN_EXECUTION
    ),
    FlowSchemaModelEntry(
        flow_tables.FlowRunStepResultFiles, FlowSchemaAggregate.RUN_EXECUTION
    ),
    FlowSchemaModelEntry(
        flow_tables.FlowRunAuditOutbox, FlowSchemaAggregate.RUN_EXECUTION
    ),
    FlowSchemaModelEntry(
        flow_tables.FlowRunWebhookDeliveries, FlowSchemaAggregate.RUN_EXECUTION
    ),
    FlowSchemaModelEntry(
        flow_tables.FlowRunReviewCheckpoints, FlowSchemaAggregate.REVIEW_AND_RERUN
    ),
    FlowSchemaModelEntry(
        flow_tables.FlowRunRerunOperations, FlowSchemaAggregate.REVIEW_AND_RERUN
    ),
    FlowSchemaModelEntry(
        flow_tables.FlowRunRerunInvalidatedSteps,
        FlowSchemaAggregate.REVIEW_AND_RERUN,
    ),
    FlowSchemaModelEntry(
        FlowClassificationRetentionPolicies, FlowSchemaAggregate.RETENTION
    ),
    FlowSchemaModelEntry(
        flow_tables.BuilderSessions, FlowSchemaAggregate.DEFERRED_ADJACENT
    ),
    FlowSchemaModelEntry(
        flow_tables.BuilderPlans, FlowSchemaAggregate.DEFERRED_ADJACENT
    ),
    FlowSchemaModelEntry(
        flow_tables.BuilderSessionFiles, FlowSchemaAggregate.DEFERRED_ADJACENT
    ),
    FlowSchemaModelEntry(
        flow_tables.FlowPackageImports, FlowSchemaAggregate.DEFERRED_ADJACENT
    ),
)

FLOW_SCHEMA_BOUNDARY_TABLE_NAMES = frozenset(
    {
        "api_keys_v2",
        "assistants",
        "files",
        "jobs",
        "security_classifications",
        "service_principals",
        "spaces",
        "tenants",
        "users",
    }
)

_AGGREGATE_DESCRIPTIONS = {
    FlowSchemaAggregate.FLOW_DEFINITION: (
        "The draft Flow an author edits, the immutable published versions "
        "runs execute, the step graph, DOCX templates, and the tenant-local "
        "resources a Flow is bound to."
    ),
    FlowSchemaAggregate.RUN_EXECUTION: (
        "One row per run, per step result, per attempt, and per provider "
        "call, plus the files a run reads and produces, and the two outboxes "
        "(audit, webhook) that deliver after the run transaction commits."
    ),
    FlowSchemaAggregate.REVIEW_AND_RERUN: (
        "Human review checkpoints and rerun operations. Reruns invalidate "
        "downstream steps and link the new attempts to the old ones instead "
        "of deleting history."
    ),
    FlowSchemaAggregate.RETENTION: (
        "Per-classification retention rules. `data_retention_days` activates "
        "automatic run-history deletion; `minimum_retention_days` and "
        "`no_purge` only block deletion, they never activate it."
    ),
    FlowSchemaAggregate.DEFERRED_ADJACENT: (
        "AI Builder sessions and Flow package imports. They reference Flow "
        "tables but are not part of the run or history model."
    ),
}


# Aggregates whose relationship diagram would still be too dense as one figure
# are drawn as named parts; every table of the aggregate must appear in exactly
# one part.
_AGGREGATE_DIAGRAM_PARTS: dict[
    FlowSchemaAggregate, tuple[tuple[str, frozenset[str]], ...]
] = {
    FlowSchemaAggregate.RUN_EXECUTION: (
        (
            "Runs, step results, attempts, and provider calls",
            frozenset(
                {
                    "flow_runs",
                    "flow_step_results",
                    "flow_step_attempts",
                    "flow_step_attempt_resolved_inputs",
                    "flow_provider_calls",
                }
            ),
        ),
        (
            "Files and delivery outboxes",
            frozenset(
                {
                    "flow_runtime_uploaded_files",
                    "flow_run_step_input_files",
                    "flow_run_step_result_files",
                    "flow_run_audit_outbox",
                    "flow_run_webhook_deliveries",
                }
            ),
        ),
    ),
}


@dataclass(frozen=True, slots=True)
class FlowSchemaTableDoc:
    model_name: str
    table: sa.Table
    stores: str
    writer: str
    purpose: str
    aggregate: FlowSchemaAggregate

    @property
    def table_name(self) -> str:
        return self.table.name


@dataclass(frozen=True, slots=True)
class FlowSchemaRelationshipDoc:
    source_table_name: str
    target_table_name: str
    source_cardinality: str
    target_cardinality: str
    local_column_names: tuple[str, ...]
    ondelete: str

    @property
    def sort_key(self) -> tuple[str, str, tuple[str, ...], str]:
        return (
            self.source_table_name,
            self.target_table_name,
            self.local_column_names,
            self.ondelete,
        )


def parse_flow_schema_model_docstring(
    model: type[object],
    *,
    table_name: str,
) -> tuple[str, str, str]:
    raw_doc = model.__dict__.get("__doc__")
    if not isinstance(raw_doc, str) or not raw_doc.strip():
        raise ValueError(
            f"Flow schema table {table_name} must define a model docstring"
        )

    doc = " ".join(inspect.cleandoc(raw_doc).split())
    if not doc.startswith("Stores "):
        raise ValueError(
            f"Flow schema table {table_name} docstring must start with 'Stores '"
        )
    if _WRITER_MARKER not in doc or _PURPOSE_MARKER not in doc:
        raise ValueError(
            f"Flow schema table {table_name} docstring must contain "
            "'Writer:' and 'Purpose:' markers"
        )

    stores, writer_and_purpose = doc[len("Stores ") :].split(_WRITER_MARKER, 1)
    writer, purpose = writer_and_purpose.split(_PURPOSE_MARKER, 1)
    if not stores.strip() or not writer.strip() or not purpose.strip():
        raise ValueError(
            f"Flow schema table {table_name} docstring has an empty summary field"
        )

    return stores.strip(), writer.strip(), purpose.strip()


def discover_flow_schema_tables() -> tuple[FlowSchemaTableDoc, ...]:
    import_module("eneo.database.tables")

    table_docs: list[FlowSchemaTableDoc] = []
    seen_table_names: set[str] = set()
    for entry in FLOW_SCHEMA_MODEL_REGISTRY:
        table = cast(sa.Table | None, getattr(entry.model, "__table__", None))
        if table is None or table.name in seen_table_names:
            raise ValueError(
                f"Flow schema registry has duplicate or unmapped table {entry.model}"
            )

        seen_table_names.add(table.name)
        stores, writer, purpose = parse_flow_schema_model_docstring(
            entry.model,
            table_name=table.name,
        )
        table_docs.append(
            FlowSchemaTableDoc(
                model_name=entry.model.__name__,
                table=table,
                stores=stores,
                writer=writer,
                purpose=purpose,
                aggregate=entry.aggregate,
            )
        )

    return tuple(
        sorted(
            table_docs,
            key=lambda table_doc: (
                list(FlowSchemaAggregate).index(table_doc.aggregate),
                table_doc.table_name,
            ),
        )
    )


def render_flow_schema_docs_page() -> str:
    table_docs = discover_flow_schema_tables()
    _assert_tenant_edges_cascade(table_docs)

    parts = [
        FLOW_DOCS_RELATED_NEXTRA_CARDS_IMPORT,
        "",
        "# The data schema",
        "",
        "Use this page before changing Flow tables, retention, or JSONB. It shows which tables belong together, how rows are deleted, which module writes each table, and which typed owner reads each JSONB column.",
        "",
        "Generated from SQLAlchemy metadata and the Flow JSONB ownership "
        "registry; run `make docs:regen` from the repository root after a "
        "schema or JSONB ownership change. Model classes live in "
        "`backend/src/eneo/database/tables/` and are named after their tables "
        "(`flow_runs` is `FlowRuns`).",
        "",
        "## How to read the diagrams",
        "",
        "- One line per pair of tables. The label is the `ON DELETE` rule; "
        "when a table references the same target through more than one "
        "foreign key, the label also names the column. Composite foreign "
        "keys that repeat a simpler one (`flow_id` and `flow_id, tenant_id`) "
        "are drawn once, and the column lists show only the half that "
        "identifies the parent row; the other half pins the child to its "
        "parent's tenant or flow.",
        f"- Every table with a `{_TENANT_COLUMN_NAME}` column references "
        f"`{_TENANT_TABLE_NAME}` with `ON DELETE CASCADE`. Those lines are "
        "omitted; deleting a tenant deletes all of its Flow rows. Likewise, "
        f"every table that references `{_RUN_TABLE_NAME}` also references "
        f"`{_FLOW_TABLE_NAME}` with the same rule; only the run line is drawn.",
        "- Crow's foot marks the side that holds the foreign key: `}o` many "
        "rows, `|o` at most one. On the referenced side `||` means the "
        "column is required and `o|` means it is nullable.",
        "- Tables owned outside Flows (`users`, `files`, `spaces`, ...) and "
        "Flow tables from another aggregate are drawn as plain boxes. Every "
        "column, key, and foreign key is listed under **Columns** in each "
        "section.",
        "",
        "## Aggregates",
        "",
        _render_aggregate_map(),
        "",
        _render_aggregate_inventory(table_docs),
        "",
        _render_aggregate_sections(table_docs),
        "",
        "## JSONB columns",
        "",
        "Every Flow JSONB column has one typed owner. `Invalid payload` says what "
        "a reader does with a stored value the owner cannot parse.",
        "",
        _render_jsonb_policy(),
        "",
        "## Related",
        "",
        render_flow_docs_related_nextra_cards(
            (
                FlowDocsRelatedNextraCard(
                    "Key decisions",
                    "/docs/flows-for-developers/key-decisions",
                ),
                FlowDocsRelatedNextraCard(
                    "Reviewing Flows code",
                    "/docs/flows-for-developers/reviewing-flows-code",
                ),
            )
        ),
        "",
    ]
    return "\n".join(parts)


def write_flow_schema_docs_page(
    output_path: Path = FLOW_DEVELOPER_SCHEMA_DOCS_OUTPUT_PATH,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_flow_schema_docs_page(), encoding="utf-8")


def _assert_tenant_edges_cascade(table_docs: tuple[FlowSchemaTableDoc, ...]) -> None:
    """The page states this rule once instead of drawing the edges; keep it true."""
    for table_doc in table_docs:
        if _TENANT_COLUMN_NAME not in table_doc.table.c:
            continue
        tenant_constraints = [
            constraint
            for constraint in table_doc.table.foreign_key_constraints
            if constraint.referred_table.name == _TENANT_TABLE_NAME
        ]
        if not tenant_constraints or any(
            constraint.ondelete != "CASCADE" for constraint in tenant_constraints
        ):
            raise ValueError(
                f"{table_doc.table_name}.{_TENANT_COLUMN_NAME} must reference "
                f"{_TENANT_TABLE_NAME} with ondelete=CASCADE; the schema docs "
                "state that rule for every table"
            )


# --- aggregate overview -----------------------------------------------------


def _render_aggregate_map() -> str:
    lines = ["flowchart LR"]
    for aggregate in FlowSchemaAggregate:
        lines.append(f'  {_aggregate_node_id(aggregate)}["{aggregate.value}"]')
    lines.extend(_aggregate_map_relationship_lines(FLOW_SCHEMA_MODEL_REGISTRY))
    return render_flow_docs_mermaid_block(*lines)


def _aggregate_map_relationship_lines(
    model_registry: tuple[FlowSchemaModelEntry, ...],
) -> tuple[str, ...]:
    edges = _aggregate_map_edges(model_registry)
    aggregate_order = {
        aggregate: index for index, aggregate in enumerate(FlowSchemaAggregate)
    }
    rendered_pairs: set[frozenset[FlowSchemaAggregate]] = set()
    lines: list[str] = []

    for source_aggregate, target_aggregate in sorted(
        edges,
        key=lambda edge: (aggregate_order[edge[0]], aggregate_order[edge[1]]),
    ):
        pair = frozenset((source_aggregate, target_aggregate))
        if pair in rendered_pairs:
            continue
        rendered_pairs.add(pair)

        if (target_aggregate, source_aggregate) in edges:
            left, right = sorted(pair, key=lambda aggregate: aggregate_order[aggregate])
            lines.append(
                f"  {_aggregate_node_id(left)} <--> {_aggregate_node_id(right)}"
            )
            continue

        lines.append(
            f"  {_aggregate_node_id(source_aggregate)} --> "
            f"{_aggregate_node_id(target_aggregate)}"
        )

    return tuple(lines)


def _aggregate_map_edges(
    model_registry: tuple[FlowSchemaModelEntry, ...],
) -> frozenset[tuple[FlowSchemaAggregate, FlowSchemaAggregate]]:
    aggregate_by_table_name: dict[str, FlowSchemaAggregate] = {}
    for entry in model_registry:
        table = cast(sa.Table | None, getattr(entry.model, "__table__", None))
        if table is None:
            raise ValueError(f"Flow schema registry entry {entry.model} has no table")
        aggregate_by_table_name[table.name] = entry.aggregate

    edges: set[tuple[FlowSchemaAggregate, FlowSchemaAggregate]] = set()

    for entry in model_registry:
        source_table = cast(sa.Table | None, getattr(entry.model, "__table__", None))
        if source_table is None:
            raise ValueError(f"Flow schema registry entry {entry.model} has no table")
        for constraint in source_table.foreign_key_constraints:
            target_aggregate = aggregate_by_table_name.get(
                constraint.referred_table.name
            )
            if target_aggregate is None or target_aggregate is entry.aggregate:
                continue
            edges.add((entry.aggregate, target_aggregate))

    return frozenset(edges)


def _aggregate_node_id(aggregate: FlowSchemaAggregate) -> str:
    return aggregate.name.lower()


def _flow_docs_heading_slug(value: str) -> str:
    cleaned = "".join(
        char.lower() for char in value if char.isalnum() or char in (" ", "-", "_")
    )
    return "-".join(cleaned.split())


def _aggregate_heading_href(aggregate: FlowSchemaAggregate) -> str:
    return f"#{_flow_docs_heading_slug(aggregate.value)}"


def _render_aggregate_inventory(table_docs: tuple[FlowSchemaTableDoc, ...]) -> str:
    rows: list[tuple[str, ...]] = []
    for aggregate in FlowSchemaAggregate:
        aggregate_table_docs = _table_docs_for_aggregate(table_docs, aggregate)
        rows.append(
            (
                f"[{aggregate.value}]({_aggregate_heading_href(aggregate)})",
                _markdown_cell(_AGGREGATE_DESCRIPTIONS[aggregate]),
                ", ".join(
                    f"`{table_doc.table_name}`" for table_doc in aggregate_table_docs
                ),
            )
        )

    return _render_markdown_table(("Aggregate", "What it owns", "Tables"), rows)


# --- per-aggregate sections -------------------------------------------------


def _render_aggregate_sections(
    table_docs: tuple[FlowSchemaTableDoc, ...],
) -> str:
    parts: list[str] = []
    for aggregate in FlowSchemaAggregate:
        aggregate_table_docs = _table_docs_for_aggregate(table_docs, aggregate)
        parts.extend(
            (
                f"## {aggregate.value}",
                "",
                _AGGREGATE_DESCRIPTIONS[aggregate],
                "",
                _render_aggregate_diagrams(
                    aggregate, aggregate_table_docs, all_table_docs=table_docs
                ),
                "",
                _render_table_summary(aggregate_table_docs),
                "",
                _render_column_details(aggregate_table_docs),
                "",
            )
        )
        if aggregate is FlowSchemaAggregate.REVIEW_AND_RERUN:
            parts.extend(
                (
                    "`flow_run_review_checkpoints.schema_version` versions the persisted review payload",
                    "contract. An edit submits only the step's own value: a string for a `text` output",
                    "step, or a JSON object or array for a `json` output step, checked against the",
                    "snapshotted `output_contract_json`. The server rebuilds `current_payload_json`",
                    "around that value, deriving a JSON step's `text` from `structured` so the two",
                    "encodings cannot disagree, and carrying every runtime-owned key over from the",
                    "stored payload. A checkpoint whose `review_mode` is `view`, and an output whose",
                    "text overflowed into a generated file, refuse the edit; PDF and DOCX",
                    "artifact-producing steps may persist view checkpoints but cannot publish an",
                    "edit review policy.",
                    "",
                )
            )

    return "\n".join(parts).rstrip()


def _table_docs_for_aggregate(
    table_docs: tuple[FlowSchemaTableDoc, ...],
    aggregate: FlowSchemaAggregate,
) -> tuple[FlowSchemaTableDoc, ...]:
    return tuple(
        table_doc for table_doc in table_docs if table_doc.aggregate is aggregate
    )


def _render_aggregate_diagrams(
    aggregate: FlowSchemaAggregate,
    table_docs: tuple[FlowSchemaTableDoc, ...],
    *,
    all_table_docs: tuple[FlowSchemaTableDoc, ...],
) -> str:
    parts = _AGGREGATE_DIAGRAM_PARTS.get(aggregate)
    if parts is None:
        return _render_er_diagram(table_docs, all_table_docs=all_table_docs)

    covered = [name for _, names in parts for name in names]
    if sorted(covered) != sorted(table_doc.table_name for table_doc in table_docs):
        raise ValueError(
            f"Diagram parts for {aggregate.value} must cover each table exactly once"
        )

    rendered: list[str] = []
    for title, names in parts:
        part_docs = tuple(doc for doc in table_docs if doc.table_name in names)
        rendered.extend(
            (
                f"**{title}**",
                "",
                _render_er_diagram(part_docs, all_table_docs=all_table_docs),
                "",
            )
        )
    return "\n".join(rendered).rstrip()


def _render_er_diagram(
    table_docs: tuple[FlowSchemaTableDoc, ...],
    *,
    all_table_docs: tuple[FlowSchemaTableDoc, ...],
) -> str:
    flow_table_names = {table_doc.table_name for table_doc in all_table_docs}
    relationships: list[FlowSchemaRelationshipDoc] = []

    for table_doc in table_docs:
        for constraint in _sorted_foreign_keys(table_doc.table):
            relationship = _flow_schema_relationship_from_constraint(constraint)
            target = relationship.target_table_name
            if target not in flow_table_names and (
                target not in FLOW_SCHEMA_BOUNDARY_TABLE_NAMES
            ):
                raise ValueError(
                    "Flow schema docs boundary table allowlist is missing "
                    f"foreign key target {target}"
                )
            if target == _TENANT_TABLE_NAME:
                continue
            relationships.append(relationship)

    relationships = _without_implied_flow_edges(relationships)

    edges = _diagram_edges(relationships)
    drawn = {
        name
        for relationship in relationships
        for name in (relationship.source_table_name, relationship.target_table_name)
        if name != _TENANT_TABLE_NAME
    }
    lines = ["erDiagram"]
    for table_doc in sorted(table_docs, key=lambda table_doc: table_doc.table_name):
        if table_doc.table_name not in drawn:
            # A table with no drawn relationship still needs to appear.
            lines.append(f"  {_mermaid_entity_name(table_doc.table_name)} {{ }}")
    lines.extend(edges)

    return render_flow_docs_mermaid_block(*lines)


def _without_implied_flow_edges(
    relationships: list[FlowSchemaRelationshipDoc],
) -> list[FlowSchemaRelationshipDoc]:
    """Drop `-> flows` edges implied by a `-> flow_runs` edge with the same rule.

    Every run-child table carries `flow_id` next to `flow_run_id`; the page
    states that once instead of drawing it on each table.
    """
    run_rule_by_source: dict[str, set[str]] = defaultdict(set)
    for relationship in relationships:
        if relationship.target_table_name == _RUN_TABLE_NAME:
            run_rule_by_source[relationship.source_table_name].add(
                relationship.ondelete
            )
    return [
        relationship
        for relationship in relationships
        if not (
            relationship.target_table_name == _FLOW_TABLE_NAME
            and relationship.ondelete
            in run_rule_by_source[relationship.source_table_name]
        )
    ]


def _diagram_edges(relationships: list[FlowSchemaRelationshipDoc]) -> list[str]:
    """One edge per semantic foreign key.

    Constraints from one table to one target whose local columns overlap
    (`flow_id` and `flow_id, tenant_id`) are the same relationship written
    twice for composite integrity; they are drawn once, using the constraint
    with the fewest columns. Constraints with disjoint columns (`created_by_user_id`
    and `owner_user_id`) are distinct relationships and each keep their column
    in the label.
    """
    by_pair: dict[tuple[str, str], list[FlowSchemaRelationshipDoc]] = defaultdict(list)
    for relationship in relationships:
        by_pair[
            (relationship.source_table_name, relationship.target_table_name)
        ].append(relationship)

    edges: list[str] = []
    for (source, target), pair_relationships in sorted(by_pair.items()):
        groups = _semantic_groups(pair_relationships)
        for group in groups:
            representative = min(
                group, key=lambda item: (len(item.local_column_names), item.sort_key)
            )
            rules = sorted({item.ondelete for item in group})
            label = " / ".join(rules)
            if len(groups) > 1:
                label = f"{representative.local_column_names[0]}: {label}"
            edges.append(
                f"  {_mermaid_entity_name(source)} "
                f"{representative.source_cardinality}--"
                f"{representative.target_cardinality} "
                f'{_mermaid_entity_name(target)} : "{label}"'
            )
    return edges


def _semantic_groups(
    relationships: list[FlowSchemaRelationshipDoc],
) -> list[list[FlowSchemaRelationshipDoc]]:
    groups: list[list[FlowSchemaRelationshipDoc]] = []
    for relationship in sorted(relationships, key=lambda item: item.sort_key):
        columns = set(relationship.local_column_names)
        for group in groups:
            if any(columns & set(member.local_column_names) for member in group):
                group.append(relationship)
                break
        else:
            groups.append([relationship])
    return groups


def _render_table_summary(table_docs: tuple[FlowSchemaTableDoc, ...]) -> str:
    rows: list[tuple[str, ...]] = []
    for table_doc in table_docs:
        rows.append(
            (
                f"`{table_doc.table_name}`",
                _markdown_cell(_sentence(table_doc.stores)),
                _markdown_cell(table_doc.writer.rstrip(".")),
                _markdown_cell(_sentence(table_doc.purpose)),
            )
        )

    return _render_markdown_table(
        ("Table", "Stores", "Written by", "Why it exists"),
        rows,
    )


def _render_column_details(table_docs: tuple[FlowSchemaTableDoc, ...]) -> str:
    parts: list[str] = []
    for table_doc in table_docs:
        table = table_doc.table
        rows = [
            (
                f"`{column.name}`",
                _column_type_label(cast(sa.Column[object], column)),
                "yes" if column.nullable else "",
                _column_key_cell(table, cast(sa.Column[object], column)),
            )
            for column in table.columns
        ]
        body = _render_markdown_table(("Column", "Type", "Nullable", "Key"), rows)
        parts.append(
            "\n".join(
                (
                    "<details>",
                    f"<summary><code>{table.name}</code> columns ({len(rows)})</summary>",
                    "",
                    body,
                    "",
                    "</details>",
                )
            )
        )
    return "\n\n".join(parts)


def _column_key_cell(table: sa.Table, column: sa.Column[object]) -> str:
    keys: list[str] = []
    if column.primary_key:
        keys.append("PK")
    seen: set[tuple[str, str, str]] = set()
    for constraint in _sorted_foreign_keys(table):
        referred_pk = {
            element.column.name
            for element in constraint.elements
            if element.column.primary_key
        }
        for element in constraint.elements:
            if element.parent.name != column.name:
                continue
            target = element.column
            if referred_pk and target.name not in referred_pk:
                # In a composite key such as (flow_id, tenant_id) -> flows(id,
                # tenant_id) only the primary-key half identifies the row; the
                # other half pins the child to its parent's tenant or flow.
                continue
            rule = constraint.ondelete or "NO ACTION"
            key = (target.table.name, target.name, rule)
            if key in seen:
                continue
            seen.add(key)
            keys.append(f"FK → `{target.table.name}.{target.name}` {rule}")
    return "; ".join(keys)


def _flow_schema_relationship_from_constraint(
    constraint: sa.ForeignKeyConstraint,
) -> FlowSchemaRelationshipDoc:
    source_table = constraint.table
    local_column_names = tuple(column.name for column in constraint.columns)
    return FlowSchemaRelationshipDoc(
        source_table_name=source_table.name,
        target_table_name=constraint.referred_table.name,
        source_cardinality=(
            "|o"
            if _local_column_set_is_unique(source_table, local_column_names)
            else "}o"
        ),
        target_cardinality=(
            "||"
            if all(
                not source_table.c[column_name].nullable
                for column_name in local_column_names
            )
            else "o|"
        ),
        local_column_names=local_column_names,
        ondelete=constraint.ondelete or "NO ACTION",
    )


def _local_column_set_is_unique(
    table: sa.Table,
    column_names: tuple[str, ...],
) -> bool:
    local_column_names = frozenset(column_names)
    primary_key_names = frozenset(column.name for column in table.primary_key.columns)
    if primary_key_names and primary_key_names <= local_column_names:
        return True

    for constraint in table.constraints:
        if isinstance(constraint, sa.UniqueConstraint) and (
            frozenset(column.name for column in constraint.columns)
            <= local_column_names
        ):
            return True

    for index in table.indexes:
        if not index.unique or "postgresql_where" in index.dialect_kwargs:
            continue

        index_column_names = _index_column_names(index)
        if index_column_names is None:
            continue
        if frozenset(index_column_names) <= local_column_names:
            return True

    return False


def _index_column_names(index: sa.Index) -> tuple[str, ...] | None:
    column_names: list[str] = []
    for expression in index.expressions:
        if not isinstance(expression, sa.Column):
            return None
        column_names.append(expression.name)
    return tuple(column_names)


# --- JSONB ------------------------------------------------------------------


def _render_jsonb_policy() -> str:
    owners = sorted(
        FLOW_JSONB_COLUMN_OWNERS.values(),
        key=lambda owner: (owner.table_name, owner.column_name),
    )

    rows: list[tuple[str, ...]] = []
    for owner in owners:
        rows.append(
            (
                f"`{owner.table_name}.{owner.column_name}`",
                f"`{owner.envelope_name}`<br />`{owner.owner_module}`",
                f"`{owner.storage_category.value}`",
                _markdown_cell(str(owner.schema_version_policy)),
                _markdown_cell(str(owner.corruption_behavior)),
                _markdown_cell(owner.rationale),
            )
        )

    return _render_markdown_table(
        (
            "Column",
            "Envelope and owner",
            "Category",
            "Versioning",
            "Invalid payload",
            "Why JSON",
        ),
        rows,
    )


# --- helpers ----------------------------------------------------------------


def _render_markdown_table(
    headers: tuple[str, ...],
    rows: list[tuple[str, ...]],
) -> str:
    widths = [
        max(len(row[column_index]) for row in (headers, *rows))
        for column_index in range(len(headers))
    ]

    def render_row(cells: tuple[str, ...]) -> str:
        padded_cells = [
            cell.ljust(widths[column_index]) for column_index, cell in enumerate(cells)
        ]
        return f"| {' | '.join(padded_cells)} |"

    separator = tuple("-" * max(3, width) for width in widths)
    return "\n".join(
        [render_row(headers), render_row(separator), *map(render_row, rows)]
    )


def _column_type_label(column: sa.Column[object]) -> str:
    try:
        if column.type.python_type is UUID:
            return "uuid"
    except NotImplementedError:
        pass

    raw_type = str(column.type).lower().split("(", maxsplit=1)[0]
    return "".join(character if character.isalnum() else "_" for character in raw_type)


def _sorted_foreign_keys(table: sa.Table) -> list[sa.ForeignKeyConstraint]:
    return sorted(
        table.foreign_key_constraints,
        key=lambda constraint: (
            constraint.referred_table.name,
            tuple(column.name for column in constraint.columns),
        ),
    )


def _mermaid_entity_name(table_name: str) -> str:
    return table_name.replace("-", "_")


def _sentence(value: str) -> str:
    text = " ".join(value.split())
    return text[:1].upper() + text[1:] if text else text


def _markdown_cell(value: str) -> str:
    return " ".join(value.split()).replace("|", "\\|")
