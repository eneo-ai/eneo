from __future__ import annotations

import inspect
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
    FlowDocsNextraCard,
    FlowDocsRelatedNextraCard,
    render_flow_docs_anchor_shortcut_cards,
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
_BOUNDARY_NODE_LABEL = "external owner"


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

_CORE_SCHEMA_AGGREGATES = (
    FlowSchemaAggregate.FLOW_DEFINITION,
    FlowSchemaAggregate.RUN_EXECUTION,
    FlowSchemaAggregate.REVIEW_AND_RERUN,
    FlowSchemaAggregate.RETENTION,
)

_AGGREGATE_DESCRIPTIONS = {
    FlowSchemaAggregate.FLOW_DEFINITION: (
        "Authoring tables define the draft Flow, immutable published versions, "
        "step graph, templates, and local resource bindings."
    ),
    FlowSchemaAggregate.RUN_EXECUTION: (
        "Runtime tables persist runs, attempts, current step results, runtime "
        "uploads, generated files, audit delivery, and outbound HTTP delivery."
    ),
    FlowSchemaAggregate.REVIEW_AND_RERUN: (
        "Review and rerun tables preserve human checkpoints, rerun requests, "
        "and invalidation lineage without deleting earlier history."
    ),
    FlowSchemaAggregate.RETENTION: (
        "Delete-after values activate automatic run-history deletion. "
        "Minimum-retention values preserve history and no-purge values block "
        "deletion without activating it."
    ),
    FlowSchemaAggregate.DEFERRED_ADJACENT: (
        "Adjacent builder and import tables live near Flow persistence "
        "but are not core runtime/history aggregates."
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
    def label(self) -> str:
        return f"{', '.join(self.local_column_names)} ondelete={self.ondelete}"

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

    parts = [
        FLOW_DOCS_RELATED_NEXTRA_CARDS_IMPORT,
        "",
        "# The data schema",
        "",
        "Use this page before changing Flow tables, retention, or JSONB. It shows each database aggregate, delete rule, writer, and typed JSON owner.",
        "",
        "This page is generated from SQLAlchemy metadata and the Flow JSONB "
        "ownership registry. Run `make docs:regen` from the repository root "
        "after schema or JSONB ownership changes; it includes the schema docs "
        "generator.",
        "",
        "The ERDs are split by aggregate. Nodes marked "
        f"`{_BOUNDARY_NODE_LABEL}` are platform-owned tables referenced by Flow "
        "foreign keys. Relationship labels show local FK columns and delete "
        "`ondelete` behavior; `NO ACTION` can be explicit or the SQL default.",
        "",
        "## Aggregate map",
        "",
        "Single-direction links point from the aggregate that owns the foreign "
        "key to the aggregate it references; mutual links combine foreign keys "
        "in both directions. Delete behavior stays on the ERD labels below.",
        "",
        _render_aggregate_map(),
        "",
        "### ERD shortcuts",
        "",
        "Use these cards to jump to one aggregate ERD. The diagrams stay visible "
        "on the page so Mermaid can render them reliably.",
        "",
        _render_aggregate_shortcut_cards(),
        "",
        "### Tables by aggregate",
        "",
        _render_aggregate_inventory(table_docs),
        "",
        "## Aggregate entity relationship diagrams",
        "",
        _render_aggregate_er_diagram_sections(table_docs),
        "",
        "## Tables",
        "",
        _render_table_summary(table_docs),
        "",
        "## JSONB policy",
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


def _render_aggregate_map() -> str:
    lines = ["erDiagram"]
    for aggregate in FlowSchemaAggregate:
        scope = "Core" if aggregate in _CORE_SCHEMA_AGGREGATES else "Deferred adjacent"
        lines.extend(
            (
                f"  {_aggregate_node_id(aggregate)} {{",
                f'    string aggregate "{aggregate.value}"',
                f'    string scope "{scope}"',
                "  }",
            )
        )

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
        key=lambda edge: (
            aggregate_order[edge[0]],
            aggregate_order[edge[1]],
        ),
    ):
        pair = frozenset((source_aggregate, target_aggregate))
        if pair in rendered_pairs:
            continue
        rendered_pairs.add(pair)

        reverse_edge = (target_aggregate, source_aggregate)
        if reverse_edge in edges:
            left, right = sorted(pair, key=lambda aggregate: aggregate_order[aggregate])
            lines.append(
                f"  {_aggregate_node_id(left)} }}o--o{{ "
                f"{_aggregate_node_id(right)} : mutual_FKs"
            )
            continue

        lines.append(
            f"  {_aggregate_node_id(source_aggregate)} }}o--|| "
            f"{_aggregate_node_id(target_aggregate)} : references"
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


def _render_aggregate_shortcut_cards() -> str:
    cards = tuple(
        FlowDocsNextraCard(aggregate.value, _aggregate_heading_href(aggregate))
        for aggregate in FlowSchemaAggregate
    )
    return render_flow_docs_anchor_shortcut_cards(cards)


def _render_aggregate_inventory(table_docs: tuple[FlowSchemaTableDoc, ...]) -> str:
    rows: list[tuple[str, ...]] = []
    for aggregate in FlowSchemaAggregate:
        aggregate_table_docs = _table_docs_for_aggregate(table_docs, aggregate)
        rows.append(
            (
                _markdown_cell(aggregate.value),
                (
                    "Core"
                    if aggregate in _CORE_SCHEMA_AGGREGATES
                    else "Deferred adjacent"
                ),
                _markdown_cell(_AGGREGATE_DESCRIPTIONS[aggregate]),
                ", ".join(
                    f"`{table_doc.table_name}`" for table_doc in aggregate_table_docs
                ),
            )
        )

    return _render_markdown_table(
        ("Aggregate", "Scope", "What it owns", "Tables"), rows
    )


def write_flow_schema_docs_page(
    output_path: Path = FLOW_DEVELOPER_SCHEMA_DOCS_OUTPUT_PATH,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_flow_schema_docs_page(), encoding="utf-8")


def _render_aggregate_er_diagram_sections(
    table_docs: tuple[FlowSchemaTableDoc, ...],
) -> str:
    parts: list[str] = []
    for aggregate in FlowSchemaAggregate:
        aggregate_table_docs = _table_docs_for_aggregate(table_docs, aggregate)
        parts.extend(
            (
                f"### {aggregate.value}",
                "",
                _AGGREGATE_DESCRIPTIONS[aggregate],
                "",
                _render_er_diagram(
                    aggregate_table_docs,
                    all_table_docs=table_docs,
                ),
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


def _render_er_diagram(
    table_docs: tuple[FlowSchemaTableDoc, ...],
    *,
    all_table_docs: tuple[FlowSchemaTableDoc, ...],
) -> str:
    lines = ["erDiagram"]
    aggregate_table_names = {table_doc.table_name for table_doc in table_docs}
    flow_table_names = {table_doc.table_name for table_doc in all_table_docs}
    context_table_names: set[str] = set()
    boundary_table_names: set[str] = set()
    relationships: list[FlowSchemaRelationshipDoc] = []

    for table_doc in table_docs:
        for constraint in table_doc.table.foreign_key_constraints:
            relationship = _flow_schema_relationship_from_constraint(constraint)
            if relationship.target_table_name in flow_table_names:
                relationships.append(relationship)
                if relationship.target_table_name not in aggregate_table_names:
                    context_table_names.add(relationship.target_table_name)
            elif relationship.target_table_name in FLOW_SCHEMA_BOUNDARY_TABLE_NAMES:
                relationships.append(relationship)
                boundary_table_names.add(relationship.target_table_name)
            else:
                raise ValueError(
                    "Flow schema docs boundary table allowlist is missing "
                    f"foreign key target {relationship.target_table_name}"
                )

    for table_doc in sorted(table_docs, key=lambda table_doc: table_doc.table_name):
        _append_table_entity(lines, table_doc.table)
    for table_name in sorted(context_table_names):
        _append_context_entity(lines, table_name)
    for table_name in sorted(boundary_table_names):
        _append_boundary_entity(lines, table_name)

    for relationship in sorted(relationships, key=lambda item: item.sort_key):
        lines.append(
            f"  {_mermaid_entity_name(relationship.source_table_name)} "
            f"{relationship.source_cardinality}--"
            f"{relationship.target_cardinality} "
            f"{_mermaid_entity_name(relationship.target_table_name)} : "
            f'"{relationship.label}"'
        )

    return render_flow_docs_mermaid_block(*lines)


def _append_table_entity(lines: list[str], table: sa.Table) -> None:
    lines.append(f"  {_mermaid_entity_name(table.name)} {{")
    for column in table.columns:
        column = cast(sa.Column[object], column)
        primary_key = " PK" if column.primary_key else ""
        nullable = "nullable" if column.nullable else "required"
        lines.append(
            f'    {_column_type_label(column)} {column.name}{primary_key} "{nullable}"'
        )
    lines.append("  }")


def _append_context_entity(lines: list[str], table_name: str) -> None:
    lines.append(f"  {_mermaid_entity_name(table_name)} {{")
    lines.append('    string context "Flow table; see its aggregate"')
    lines.append("  }")


def _append_boundary_entity(lines: list[str], table_name: str) -> None:
    lines.append(f"  {_mermaid_entity_name(table_name)} {{")
    lines.append(f'    string boundary "{_BOUNDARY_NODE_LABEL}"')
    lines.append("  }")


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


def _render_table_summary(table_docs: tuple[FlowSchemaTableDoc, ...]) -> str:
    rows: list[tuple[str, ...]] = []
    for table_doc in table_docs:
        rows.append(
            (
                f"`{table_doc.table_name}`",
                f"`{table_doc.model_name}`",
                _markdown_cell(table_doc.aggregate.value),
                _markdown_cell(table_doc.stores),
                _markdown_cell(table_doc.writer),
                _markdown_cell(table_doc.purpose),
            )
        )

    return _render_markdown_table(
        (
            "Table",
            "Model",
            "Aggregate",
            "What it stores",
            "Primary writer",
            "Why it exists",
        ),
        rows,
    )


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
                f"`{owner.envelope_name}`",
                f"`{owner.owner_module}`",
                f"`{owner.storage_category.value}`",
                _markdown_cell(str(owner.schema_version_policy)),
                _markdown_cell(str(owner.corruption_behavior)),
                "yes" if owner.relational_candidate else "no",
                _markdown_cell(owner.rationale),
            )
        )

    return _render_markdown_table(
        (
            "Column",
            "Envelope",
            "Owner",
            "Category",
            "Version behavior",
            "Invalid-payload behavior",
            "Relational candidate",
            "Rationale",
        ),
        rows,
    )


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


def _mermaid_entity_name(table_name: str) -> str:
    return table_name.replace("-", "_")


def _markdown_cell(value: str) -> str:
    return " ".join(value.split()).replace("|", "\\|")
