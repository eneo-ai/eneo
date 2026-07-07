from __future__ import annotations

import configparser
import sys
from pathlib import Path
from typing import NamedTuple

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
BACKEND_SRC = BACKEND_ROOT / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

from eneo.flows.infrastructure.flow_docs_mermaid import (  # noqa: E402
    render_flow_docs_mermaid_block,
)
from eneo.flows.infrastructure.flow_docs_related_cards import (  # noqa: E402
    FLOW_DOCS_RELATED_NEXTRA_CARDS_IMPORT,
    FlowDocsRelatedNextraCard,
    render_flow_docs_related_nextra_cards,
)

FLOW_ROOT = BACKEND_ROOT / "src" / "eneo" / "flows"
PACKAGE_LAYOUT_DOC = REPO_ROOT / "docs" / "flows" / "package-layout.md"
IMPORTLINTER_CONFIG = BACKEND_ROOT / ".importlinter"
FLOW_DEVELOPER_ARCHITECTURE_DOCS_OUTPUT_PATH = (
    REPO_ROOT
    / "frontend"
    / "apps"
    / "docs-site"
    / "src"
    / "content"
    / "docs"
    / "flows-for-developers"
    / "how-built.mdx"
)

ALLOWED_LAYOUT_KINDS = frozenset({"module", "package"})
ALLOWED_TARGET_HOMES = frozenset(
    {
        "api",
        "application",
        "canonical-home",
        "domain",
        "infrastructure",
        "plugin",
        "remove-merge-later",
        "runtime",
    }
)
FLOW_ENGINE_IMPORTLINTER_CONTRACT = "importlinter:contract:flows-engine-no-ai-builder"


class FlowPackageLayoutRow(NamedTuple):
    entry: str
    kind: str
    target_home: str
    rationale: str


class ImportLinterContract(NamedTuple):
    section: str
    name: str
    contract_type: str
    source_modules: tuple[str, ...]
    forbidden_modules: tuple[str, ...]
    ignore_imports: tuple[str, ...]


def split_markdown_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def parse_target_home_descriptions(
    package_layout_doc: Path = PACKAGE_LAYOUT_DOC,
) -> dict[str, str]:
    lines = package_layout_doc.read_text(encoding="utf-8").splitlines()
    descriptions: dict[str, str] = {}
    in_section = False

    for line in lines:
        stripped = line.strip()
        if stripped == "Allowed target homes:":
            in_section = True
            continue
        if in_section and stripped.startswith("| Entry |"):
            break
        if not in_section or not stripped.startswith("- `"):
            continue

        key_and_description = stripped.removeprefix("- `")
        key, separator, description = key_and_description.partition("`: ")
        if not separator:
            raise ValueError(
                f"Malformed target-home row in {package_layout_doc}: {line}"
            )
        descriptions[key] = description.rstrip(".")

    missing = ALLOWED_TARGET_HOMES - set(descriptions)
    stale = set(descriptions) - ALLOWED_TARGET_HOMES
    if missing or stale:
        raise ValueError(
            f"{package_layout_doc} target-home descriptions are out of sync. "
            f"Missing: {sorted(missing)}; stale: {sorted(stale)}"
        )
    return descriptions


def parse_package_layout_decision_table(
    package_layout_doc: Path = PACKAGE_LAYOUT_DOC,
) -> dict[tuple[str, str], FlowPackageLayoutRow]:
    lines = package_layout_doc.read_text(encoding="utf-8").splitlines()
    table_start: int | None = None

    for index, line in enumerate(lines):
        cells = split_markdown_table_row(line)
        normalized = [cell.lower() for cell in cells]
        if normalized[:4] == ["entry", "kind", "target home", "rationale"]:
            table_start = index
            break

    if table_start is None:
        raise AssertionError(f"{package_layout_doc} must define the layout table")

    separator_index = table_start + 1
    if separator_index >= len(lines):
        raise AssertionError(f"{package_layout_doc} layout table has no separator")
    if not set(lines[separator_index].replace("|", "").strip()) <= {":", "-", " "}:
        raise AssertionError(
            f"{package_layout_doc} layout table separator is malformed"
        )

    rows: dict[tuple[str, str], FlowPackageLayoutRow] = {}
    for line in lines[separator_index + 1 :]:
        if not line.strip().startswith("|"):
            break

        cells = split_markdown_table_row(line)
        if len(cells) < 4:
            raise AssertionError(f"{package_layout_doc} has a malformed row: {line}")
        entry, kind, target_home, rationale = cells[:4]
        if not entry:
            raise AssertionError(f"{package_layout_doc} has an empty entry")
        if kind not in ALLOWED_LAYOUT_KINDS:
            raise AssertionError(
                f"{entry} uses unknown layout kind {kind!r}; "
                f"allowed values: {sorted(ALLOWED_LAYOUT_KINDS)}"
            )
        if target_home not in ALLOWED_TARGET_HOMES:
            raise AssertionError(
                f"{entry} uses unknown target home {target_home!r}; "
                f"allowed values: {sorted(ALLOWED_TARGET_HOMES)}"
            )
        if not rationale:
            raise AssertionError(f"{package_layout_doc} has no rationale for {entry}")

        key = (entry, kind)
        if key in rows:
            raise AssertionError(f"{package_layout_doc} repeats {entry!r} as {kind!r}")
        rows[key] = FlowPackageLayoutRow(
            entry=entry,
            kind=kind,
            target_home=target_home,
            rationale=rationale,
        )

    if not rows:
        raise AssertionError(f"{package_layout_doc} layout table must contain entries")
    return rows


def discover_flow_root_layout_entries(
    flow_root: Path = FLOW_ROOT,
) -> set[tuple[str, str]]:
    entries: set[tuple[str, str]] = set()

    for path in flow_root.iterdir():
        if path.name == "__pycache__":
            continue
        if path.is_dir():
            entries.add((path.name, "package"))
            continue
        if path.suffix == ".py" and path.name != "__init__.py":
            entries.add((path.stem, "module"))

    return entries


def parse_importlinter_contracts(
    importlinter_config: Path = IMPORTLINTER_CONFIG,
) -> tuple[ImportLinterContract, ...]:
    parser = configparser.ConfigParser()
    parser.read(importlinter_config, encoding="utf-8")

    contracts: list[ImportLinterContract] = []
    for section in parser.sections():
        if not section.startswith("importlinter:contract:"):
            continue
        contracts.append(
            ImportLinterContract(
                section=section,
                name=parser.get(section, "name"),
                contract_type=parser.get(section, "type"),
                source_modules=_parse_multiline_config_value(
                    parser.get(section, "source_modules", fallback="")
                ),
                forbidden_modules=_parse_multiline_config_value(
                    parser.get(section, "forbidden_modules", fallback="")
                ),
                ignore_imports=_parse_multiline_config_value(
                    parser.get(section, "ignore_imports", fallback="")
                ),
            )
        )

    return tuple(contracts)


def render_flow_developer_architecture_docs_page() -> str:
    target_home_descriptions = parse_target_home_descriptions()
    layout_rows = tuple(
        sorted(
            parse_package_layout_decision_table().values(),
            key=lambda row: (row.target_home, row.kind, row.entry),
        )
    )
    importlinter_contracts = parse_importlinter_contracts()

    parts = [
        FLOW_DOCS_RELATED_NEXTRA_CARDS_IMPORT,
        "",
        "# How Flows is built",
        "",
        "Start here when you need to change Flow code. The layer map shows the package owner, import boundary, and first module to open.",
        "",
        "## Layer map",
        "",
        _render_layer_map(),
        "",
        "This map is a target ownership model, not a promise that every module "
        "already lives under that directory. Use the grouped module tables below "
        "for the current root entry and its target-home group.",
        "",
        "## Import boundaries",
        "",
        "Import-linter enforces package dependency boundaries. Runtime policies "
        "enforce tenant and principal access before data leaves the backend.",
        "",
        _render_importlinter_contracts(importlinter_contracts),
        "",
        "## Runtime access enforcement",
        "",
        _render_runtime_access_enforcement(),
        "",
        "## Target homes",
        "",
        _render_target_home_table(target_home_descriptions),
        "",
        "## AI Builder create compile spine",
        "",
        _render_ai_builder_create_compile_spine(),
        "",
        "## Change index",
        "",
        "This is the coarse module index. Use [Reviewing Flows code](/docs/flows-for-developers/reviewing-flows-code) for the ordered procedure and validation sequence.",
        "",
        _render_change_index_table(),
        "",
        "## Module ownership",
        "",
        _render_module_ownership_table(layout_rows),
        "",
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
                    "Reviewing Flows code",
                    "/docs/flows-for-developers/reviewing-flows-code",
                ),
            )
        ),
        "",
    ]
    return "\n".join(parts)


def write_flow_developer_architecture_docs_page(
    output_path: Path = FLOW_DEVELOPER_ARCHITECTURE_DOCS_OUTPUT_PATH,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_flow_developer_architecture_docs_page(),
        encoding="utf-8",
    )


def _parse_multiline_config_value(value: str) -> tuple[str, ...]:
    return tuple(line.strip() for line in value.splitlines() if line.strip())


def _render_layer_map() -> str:
    return render_flow_docs_mermaid_block(
        "flowchart TD",
        '  api["api<br/>HTTP adapters and public schemas"] --> application["application<br/>Use cases and orchestration"]',
        '  application --> domain["domain<br/>Contracts, policies, invariants"]',
        '  application --> infrastructure["infrastructure<br/>Persistence and storage adapters"]',
        '  application --> runtime["runtime<br/>Worker execution and step handlers"]',
        "  runtime --> domain",
        "  runtime --> infrastructure",
        '  engine["Flow engine"] -.->|must not import| builder["Flow AI Builder plugin"]',
    )


def _render_importlinter_contracts(
    contracts: tuple[ImportLinterContract, ...],
) -> str:
    rows: list[tuple[str, ...]] = []
    for contract in contracts:
        rows.append(
            (
                f"`{contract.name}`",
                f"`{contract.contract_type}`",
                _source_summary(contract),
                _inline_code_list(contract.forbidden_modules),
                _inline_code_list(contract.ignore_imports)
                if contract.ignore_imports
                else "none",
            )
        )

    return _render_markdown_table(
        ("Contract", "Type", "Source", "Forbidden", "Ignored edges"),
        rows,
    )


def _render_runtime_access_enforcement() -> str:
    return "\n".join(
        [
            "`FlowRunAccessPolicy` is the first owner to inspect when a run read, "
            "cancel, rerun, artifact, or evidence path changes.",
            "",
            "- Run loads pass `tenant_id` into `FlowRunRepository.get`, so missing tenant-scoped rows stay `404`.",
            "- `FlowRunAccessPolicy.ensure_can_access_run` denies cross-tenant rows and mismatched service-key principals.",
            "- Denied access raises `flow_run_access_denied` with an `auth_layer` context value, so API consumers get a typed error instead of an internal invariant.",
            "- Runtime upload ownership uses `FlowPrincipal` and tenant-scoped repositories; do not reintroduce synthetic `UserInDB` identity in Flow runtime code.",
        ]
    )


def _render_target_home_table(target_home_descriptions: dict[str, str]) -> str:
    rows = [
        (f"`{target_home}`", _markdown_cell(description))
        for target_home, description in sorted(target_home_descriptions.items())
    ]
    return _render_markdown_table(("Target home", "Use it for"), rows)


def _render_change_index_table() -> str:
    return _render_markdown_table(
        ("Change type", "Start in", "Then check"),
        [
            (
                "AI Builder create compile shape",
                "`ai_builder_assembly`",
                "FCM, Flow validators, runtime contracts, API battle harness",
            ),
            (
                "API router or response schema",
                "`api`",
                "`application`, error metadata, generated consumer docs",
            ),
            (
                "Runtime executor or worker behavior",
                "`application`, `runtime`",
                "`domain`, persistence owner, lifecycle docs",
            ),
            (
                "Step handler or output mode",
                "`runtime`",
                "capability manifest, parser, output processing, tests",
            ),
            (
                "Runtime file or upload binding",
                "`application`, `infrastructure`",
                "file services, run contract, consumer files guide",
            ),
            (
                "Schema, migration, or JSONB boundary",
                "`infrastructure`",
                "SQLAlchemy table, JSONB owner registry, schema docs",
            ),
            (
                "FlowApiErrorCode or failure path",
                "`api`",
                "error metadata, localization, consumer error reference",
            ),
            (
                "Review checkpoint lifecycle",
                "`application`, `infrastructure`",
                "checkpoint repository, service, lifecycle docs",
            ),
            (
                "Developer docs or guarded contract",
                "`backend/scripts`, docs-site content",
                "docs generator, docs contract test, `make docs:regen`",
            ),
        ],
    )


def _render_ai_builder_create_compile_spine() -> str:
    return "\n".join(
        [
            "Create-mode AI Builder is a plugin boundary that assembles deterministic Flow mechanics before lowering. The model owns semantic intent; `FlowAssemblyPlan` owns topology, underlag channel, fixed renderer/transcription/template steps, form-field placement, source exposure, source-reader obligations, and result-contract fields that must feed the final writer.",
            "",
            render_flow_docs_mermaid_block(
                "flowchart LR",
                '  intent["CreateFlowIntent<br/>semantic steps"] --> context["CreateCompileContext<br/>server-owned architecture"]',
                '  context --> assemble["ai_builder_assembly.create<br/>topology admission"]',
                '  assemble --> plan["FlowAssemblyPlan<br/>validated mechanics"]',
                '  plan --> lower["lower_assembly_plan<br/>single writer"]',
                '  lower --> spec["FlowDraftSpecCore<br/>Flow authoring contract"]',
                '  spec --> runtime["Flow validators + runtime contracts"]',
            ),
            "",
            "- `compile_create_intent_to_spec` is the entry point; if assembly cannot support a create intent it raises `architecture_materialization_failed` instead of falling back to legacy create rewrites.",
            "- `ai_builder_assembly/create.py` admits supported topology and source exposure, `plan.py` validates `FlowAssemblyPlan`, `fixed_steps.py` owns zero-LLM planned steps, and `lower.py` is the only create-path writer of `FlowDraftSpecCore` bindings.",
            "- Do not add create-mode normalizers after `lower_assembly_plan`; update assembly rules and the API battle harness when a new Flow capability becomes authorable.",
            "- Edit mode still uses its per-step compiler path separately; do not use edit compatibility needs to reintroduce create-mode post-processing.",
        ]
    )


def _render_module_ownership_table(
    layout_rows: tuple[FlowPackageLayoutRow, ...],
) -> str:
    parts: list[str] = []
    target_homes = tuple(dict.fromkeys(row.target_home for row in layout_rows))
    for target_home in target_homes:
        target_home_rows = tuple(
            row for row in layout_rows if row.target_home == target_home
        )
        rows = [
            (
                f"`{row.entry}`",
                f"`{row.kind}`",
                _markdown_cell(row.rationale),
            )
            for row in target_home_rows
        ]
        parts.append(
            _render_details(
                f"<code>{target_home}</code> ({len(target_home_rows)} entries)",
                _render_markdown_table(
                    ("Entry", "Kind", "Owns / start here"),
                    rows,
                ),
            )
        )
    return "\n\n".join(parts)


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


def _render_source_guard_table() -> str:
    return _render_markdown_table(
        ("Guarded source", "Guard"),
        [
            (
                "`docs/flows/package-layout.md`",
                "`test_flow_package_layout.py::test_flow_root_layout_decision_matches_filesystem`",
            ),
            (
                "`backend/.importlinter` source modules",
                "`test_importlinter_boundary.py::test_source_modules_cover_every_flows_sibling`",
            ),
            (
                "this generated docs-site page",
                "`test_flow_docs_site_contract.py::test_flow_developer_docs_how_built_is_generated_from_layout_sources`",
            ),
            (
                "`backend/src/eneo/flows/application/flow_run_access_policy.py`",
                "Runtime access text names the canonical tenant and principal enforcement owner.",
            ),
        ],
    )


def _source_summary(contract: ImportLinterContract) -> str:
    if contract.section == FLOW_ENGINE_IMPORTLINTER_CONTRACT:
        return f"{len(contract.source_modules)} Flow engine root entries"
    return _inline_code_list(contract.source_modules)


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


def _inline_code_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"`{_markdown_cell(value)}`" for value in values)


def _markdown_cell(value: str) -> str:
    return " ".join(value.split()).replace("|", "\\|")
