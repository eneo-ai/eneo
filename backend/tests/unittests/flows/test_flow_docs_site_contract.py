from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import replace
from html import unescape
from pathlib import Path
from typing import Literal, Protocol, Sequence, cast

import pytest
import sqlalchemy as sa
from fastapi.routing import APIRoute

from eneo.files.file_models import (
    FILE_PUBLIC_EXAMPLE,
    SIGNED_URL_RESPONSE_EXAMPLE,
    FilePublic,
    SignedURLRequest,
    SignedURLResponse,
)
from eneo.flows.api import flow_runtime_paths as flow_runtime_path_constants
from eneo.flows.api.flow_api_error_metadata import (
    render_flow_error_taxonomy_docs_page,
)
from eneo.flows.api.flow_models import (
    FLOW_RUN_PUBLIC_EXAMPLE,
    FLOW_RUN_QUEUED_AFTER_DISPATCH_EXAMPLE,
    FLOW_RUN_REVIEW_CHECKPOINT_APPROVE_REQUEST_EXAMPLE,
    FLOW_RUN_REVIEW_CHECKPOINT_EDIT_REQUEST_EXAMPLE,
    FLOW_RUN_REVIEW_CHECKPOINT_PUBLIC_EXAMPLE,
    FLOW_RUN_REVIEW_CHECKPOINT_RESUME_REQUEST_EXAMPLE,
    FLOW_RUN_STEP_PUBLIC_EXAMPLE,
    FlowRunCreateRequest,
    FlowRunPublic,
    FlowRunReviewCheckpointEditRequest,
    FlowRunReviewCheckpointPublic,
    FlowRunReviewCheckpointResumeResponse,
    FlowRunStepPublic,
)
from eneo.flows.api.flow_router import router as flow_router
from eneo.flows.api.flow_runtime_endpoint_registry import (
    FLOW_RUNTIME_ENDPOINT_CONTRACTS,
    FlowRuntimeEndpointContract,
    FlowRuntimePathFieldProjection,
    flow_runtime_endpoint_by_operation_id,
)
from eneo.flows.api.flow_runtime_paths import (
    FLOW_ROOT_PATH,
    FlowReviewCheckpointRuntimePathsPublic,
    FlowRuntimePathsPublic,
    build_flow_endpoint_template,
    build_flow_runtime_public_example,
)
from eneo.flows.application.flow_run_lifecycle_events import (
    FLOW_RUN_LIFECYCLE_EVENT_NAME,
    FLOW_RUN_LIFECYCLE_LOG_MESSAGE,
    FLOW_RUN_TERMINALIZATION_OPERATION,
)
from eneo.flows.enums import (
    FLOW_RUN_STATUS_CAPABILITIES,
    FlowRunRerunOperationStatus,
    FlowRunReviewCheckpointState,
    FlowRunStatus,
    FlowStepAttemptStatus,
    FlowStepResultStatus,
)
from eneo.flows.flow_api_error_code import (
    FLOW_RUN_TERMINAL_ERROR_CODES,
    FLOW_TYPED_IO_ERROR_CODES,
    FlowApiErrorCode,
)
from eneo.flows.flow_capability_manifest import (
    CAPABILITY_REGISTRY,
    FINAL_OUTPUT_ARTIFACT_BY_TYPE,
)
from eneo.flows.flow_error_taxonomy import (
    FLOW_ERROR_CATEGORY_ORDER,
    FLOW_ERROR_TAXONOMY,
    FlowErrorSurface,
    FlowErrorTaxonomyEntry,
    validate_flow_error_taxonomy,
)
from eneo.flows.flow_run_contract_models import (
    FLOW_RUN_CONTRACT_PUBLIC_EXAMPLE,
    FlowFinalOutputContractPublic,
    FlowReviewStepContractPublic,
    FlowRunContractPublic,
    FlowRuntimeInputContractPublic,
    FlowRuntimeUploadPolicyPublic,
    FormFieldPublic,
)
from eneo.flows.flow_run_input_envelope import FLOW_RUN_RESERVED_INPUT_PAYLOAD_KEYS
from eneo.flows.flow_run_step_result_file import FlowRunStepResultFile
from eneo.flows.infrastructure.flow_docs_mermaid import (
    FLOW_DOCS_MERMAID_FIGURE_CLASS,
    FLOW_DOCS_MERMAID_INIT_DIRECTIVE,
    render_flow_docs_mermaid_block,
)
from eneo.flows.runtime.flow_runtime_trace import (
    FLOW_RUN_EXECUTE_SPAN_NAME,
    FLOW_RUN_SPAN_ATTRIBUTE_KEYS,
    FLOW_STEP_EXECUTE_SPAN_NAME,
    FLOW_STEP_SPAN_ATTRIBUTE_KEYS,
)
from eneo.flows.type_policies import INPUT_TYPE_POLICIES
from tests.unit.api_key_test_utils import flatten_routes

BACKEND_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = BACKEND_ROOT.parent
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
DOCS_SITE_CONTENT_ROOT = (
    REPO_ROOT / "frontend" / "apps" / "docs-site" / "src" / "content"
)
DOCS_SITE_GLOBAL_CSS = (
    REPO_ROOT / "frontend" / "apps" / "docs-site" / "src" / "app" / "globals.css"
)
FLOW_GUIDES_DIR = DOCS_SITE_CONTENT_ROOT / "guides"
FLOW_GUIDES_META = FLOW_GUIDES_DIR / "_meta.ts"
FLOW_API_GUIDE = FLOW_GUIDES_DIR / "flows-api-guide.mdx"
FLOW_CONSUMER_GUIDES_DIR = FLOW_GUIDES_DIR / "flows"
FLOW_CONSUMER_SECTION_INDEX = FLOW_CONSUMER_GUIDES_DIR / "index.mdx"
FLOW_CONSUMER_SECTION_META = FLOW_CONSUMER_GUIDES_DIR / "_meta.ts"
FLOW_CONSUMER_REFERENCE_META = FLOW_CONSUMER_GUIDES_DIR / "reference" / "_meta.ts"
FLOW_CONSUMER_ERROR_REFERENCE = FLOW_CONSUMER_GUIDES_DIR / "reference" / "errors.mdx"
FLOW_CONSUMER_DESIGNING_GUIDE = FLOW_CONSUMER_GUIDES_DIR / "designing-flows.mdx"
FLOW_CONSUMER_INTEGRATING_GUIDE = FLOW_CONSUMER_GUIDES_DIR / "integrating-flows.mdx"
FLOW_CONSUMER_FAQ_GUIDE = FLOW_CONSUMER_GUIDES_DIR / "flows-faq.mdx"
FLOW_CONSUMER_LEGACY_FLAT_GUIDES = (
    FLOW_GUIDES_DIR / "designing-flows.mdx",
    FLOW_GUIDES_DIR / "integrating-flows.mdx",
    FLOW_GUIDES_DIR / "flows-faq.mdx",
)
FLOW_CONSUMER_DELETED_FLAT_HREFS = (
    "/guides/designing-flows",
    "/guides/integrating-flows",
    "/guides/flows-faq",
)
FLOW_OVERVIEW = DOCS_SITE_CONTENT_ROOT / "docs" / "flows.mdx"
FLOW_DEVELOPER_DOCS_DIR = DOCS_SITE_CONTENT_ROOT / "docs" / "flows-for-developers"
FLOW_DEVELOPER_DOCS_DATA_SCHEMA = FLOW_DEVELOPER_DOCS_DIR / "data-schema.mdx"
FLOW_DEVELOPER_DOCS_HOW_BUILT = FLOW_DEVELOPER_DOCS_DIR / "how-built.mdx"
FLOW_DEVELOPER_DOCS_INDEX = FLOW_DEVELOPER_DOCS_DIR / "index.mdx"
FLOW_DEVELOPER_DOCS_KEY_DECISIONS = FLOW_DEVELOPER_DOCS_DIR / "key-decisions.mdx"
FLOW_DEVELOPER_DOCS_META = FLOW_DEVELOPER_DOCS_DIR / "_meta.ts"
FLOW_DEVELOPER_DOCS_REVIEWER_GUIDE = (
    FLOW_DEVELOPER_DOCS_DIR / "reviewing-flows-code.mdx"
)
FLOW_DEVELOPER_DOCS_RUN_LIFECYCLE = FLOW_DEVELOPER_DOCS_DIR / "run-lifecycle.mdx"
FLOW_DEVELOPER_DOCS_WHEN_THINGS_FAIL = FLOW_DEVELOPER_DOCS_DIR / "when-things-fail.mdx"
FLOW_DEVELOPER_DOCS_RELATED_CARD_PAGES = (
    FLOW_DEVELOPER_DOCS_HOW_BUILT,
    FLOW_DEVELOPER_DOCS_DATA_SCHEMA,
    FLOW_DEVELOPER_DOCS_RUN_LIFECYCLE,
    FLOW_DEVELOPER_DOCS_WHEN_THINGS_FAIL,
    FLOW_DEVELOPER_DOCS_KEY_DECISIONS,
    FLOW_DEVELOPER_DOCS_REVIEWER_GUIDE,
)
FLOW_DOCS_META = DOCS_SITE_CONTENT_ROOT / "docs" / "_meta.ts"
FLOW_ACCESS_MODEL_SVG = (
    REPO_ROOT
    / "frontend"
    / "apps"
    / "docs-site"
    / "public"
    / "diagrams"
    / "flows-access-model.svg"
)
DOCS_SITE_PUBLIC_DIR = REPO_ROOT / "frontend" / "apps" / "docs-site" / "public"
DOCS_SITE_DIAGRAM_PATH_PATTERN = re.compile(r"/diagrams/[^\s\"')>]+\.svg")
FRONTEND_EN_MESSAGES = REPO_ROOT / "frontend" / "apps" / "web" / "messages" / "en.json"
FLOW_OWNED_MDX_DOCS = (
    FLOW_API_GUIDE,
    FLOW_CONSUMER_SECTION_INDEX,
    FLOW_CONSUMER_ERROR_REFERENCE,
    FLOW_CONSUMER_DESIGNING_GUIDE,
    FLOW_CONSUMER_INTEGRATING_GUIDE,
    FLOW_CONSUMER_FAQ_GUIDE,
    FLOW_OVERVIEW,
    FLOW_DEVELOPER_DOCS_DATA_SCHEMA,
    FLOW_DEVELOPER_DOCS_HOW_BUILT,
    FLOW_DEVELOPER_DOCS_INDEX,
    FLOW_DEVELOPER_DOCS_KEY_DECISIONS,
    FLOW_DEVELOPER_DOCS_REVIEWER_GUIDE,
    FLOW_DEVELOPER_DOCS_RUN_LIFECYCLE,
    FLOW_DEVELOPER_DOCS_WHEN_THINGS_FAIL,
)
HAND_AUTHORED_FLOW_DOCS = (
    FLOW_API_GUIDE,
    FLOW_OVERVIEW,
    FLOW_DEVELOPER_DOCS_INDEX,
)
GENERATED_FLOW_DOCS_WITH_STANDARD_HEADER = tuple(
    path for path in FLOW_OWNED_MDX_DOCS if path not in HAND_AUTHORED_FLOW_DOCS
)
FLOW_DEVELOPER_ARCHITECTURE_DOCS_GENERATOR = (
    BACKEND_ROOT / "scripts" / "flow_developer_architecture_docs.py"
)
FLOW_DEVELOPER_LIFECYCLE_DOCS_GENERATOR = (
    BACKEND_ROOT / "scripts" / "flow_developer_lifecycle_docs.py"
)
FLOW_DEVELOPER_KEY_DECISIONS_DOCS_GENERATOR = (
    BACKEND_ROOT / "scripts" / "flow_developer_key_decisions_docs.py"
)
FLOW_DEVELOPER_REVIEWER_GUIDE_DOCS_GENERATOR = (
    BACKEND_ROOT / "scripts" / "flow_developer_reviewer_guide_docs.py"
)
FLOW_DEVELOPER_ERROR_TAXONOMY_DOCS_CATALOG = (
    BACKEND_ROOT / "src" / "eneo" / "flows" / "api" / "flow_api_error_metadata.py"
)
FLOW_DEVELOPER_SCHEMA_DOCS_GENERATOR = (
    BACKEND_ROOT
    / "src"
    / "eneo"
    / "flows"
    / "infrastructure"
    / "flow_schema_docs_exporter.py"
)
FLOW_DOCS_MERMAID_HELPER = (
    BACKEND_ROOT / "src" / "eneo" / "flows" / "infrastructure" / "flow_docs_mermaid.py"
)
FLOW_DOCS_MERMAID_GENERATOR_SOURCES = (
    FLOW_DEVELOPER_ARCHITECTURE_DOCS_GENERATOR,
    FLOW_DEVELOPER_LIFECYCLE_DOCS_GENERATOR,
    FLOW_DEVELOPER_KEY_DECISIONS_DOCS_GENERATOR,
    FLOW_DEVELOPER_REVIEWER_GUIDE_DOCS_GENERATOR,
    FLOW_DEVELOPER_ERROR_TAXONOMY_DOCS_CATALOG,
    FLOW_DEVELOPER_SCHEMA_DOCS_GENERATOR,
)
FLOW_CONSUMER_DESIGNING_GUIDE_DOCS_GENERATOR = (
    BACKEND_ROOT / "scripts" / "flow_consumer_designing_flows_docs.py"
)
FLOW_CONSUMER_INTEGRATING_GUIDE_DOCS_GENERATOR = (
    BACKEND_ROOT / "scripts" / "flow_consumer_integrating_flows_docs.py"
)
FLOW_CONSUMER_ERROR_CATALOG_DOCS_GENERATOR = (
    BACKEND_ROOT / "scripts" / "flow_consumer_error_catalog_docs.py"
)
FLOW_CONSUMER_FAQ_GUIDE_DOCS_GENERATOR = (
    BACKEND_ROOT / "scripts" / "flow_consumer_faq_docs.py"
)
FLOW_CONSUMER_SECTION_DOCS_GENERATOR = (
    BACKEND_ROOT / "scripts" / "flow_consumer_section_docs.py"
)
FLOW_DOCS_REGEN_SCRIPT = BACKEND_ROOT / "scripts" / "generate_flow_docs.py"
FLOW_DOCS_REGEN_COMMAND = "make docs:regen"

JSON_CODE_BLOCK_PATTERN = re.compile(r"```json\n(.*?)\n```", re.DOTALL)
MERMAID_CODE_BLOCK_PATTERN = re.compile(r"```mermaid\n(.*?)\n```", re.DOTALL)
PLACEHOLDER_DOC_PATTERN = re.compile(
    r"\b(todo|coming soon|placeholder|to be written)\b", re.IGNORECASE
)
FLOW_DOCS_RELATED_CARD_PATTERN = re.compile(
    r'<Cards\.Card\s+title="(?P<title>[^"]+)"\s+href="(?P<href>[^"]+)"\s+arrow\s+/>',
    re.MULTILINE,
)
FLOW_DEVELOPER_META_TITLE_PATTERN = re.compile(
    r'^\s*(?:"(?P<quoted_slug>[^"]+)"|(?P<bare_slug>[A-Za-z0-9_-]+)):\s*"(?P<title>[^"]+)",',
    re.MULTILINE,
)
RESERVED_INPUT_PAYLOAD_KEYS_PATTERN = re.compile(
    r"Reserved `input_payload_json` keys:\s*(?P<keys>[^.\n]+)\."
)
BACKTICKED_TOKEN_PATTERN = re.compile(r"`([^`]+)`")
BACKEND_SOURCE_FILE_REF_PATTERN = re.compile(r"`(backend/src/[^`]+\.py)`")
FLOW_DEVELOPER_SOURCE_FILE_REF_PATTERN = re.compile(
    r"`((?:backend|docs|frontend)/[^`]+)`"
)


class _FlowPackageLayoutRow(Protocol):
    entry: str
    kind: str
    target_home: str
    rationale: str


class _FlowDeveloperArchitectureDocsGenerator(Protocol):
    def render_flow_developer_architecture_docs_page(self) -> str: ...

    def parse_package_layout_decision_table(
        self,
    ) -> dict[tuple[str, str], _FlowPackageLayoutRow]: ...


class _FlowDeveloperLifecycleDocsGenerator(Protocol):
    STEP_RESULT_STATUS_NOTES: dict[FlowStepResultStatus, str]
    STEP_ATTEMPT_STATUS_NOTES: dict[FlowStepAttemptStatus, str]

    def render_flow_developer_lifecycle_docs_page(self) -> str: ...

    def _require_complete_state_notes(self) -> None: ...


class _FlowDecisionSourceRef(Protocol):
    label: str
    path: str


class _FlowDeveloperKeyDecision(Protocol):
    slug: str
    title: str
    context: str
    decision: str
    consequences: tuple[str, ...]
    source_refs: tuple[_FlowDecisionSourceRef, ...]


class _FlowDecisionSourceRefFactory(Protocol):
    def __call__(self, label: str, path: str) -> _FlowDecisionSourceRef: ...


class _FlowDeveloperKeyDecisionFactory(Protocol):
    def __call__(
        self,
        slug: str,
        title: str,
        context: str,
        decision: str,
        consequences: tuple[str, ...],
        source_refs: tuple[_FlowDecisionSourceRef, ...],
    ) -> _FlowDeveloperKeyDecision: ...


class _FlowDeveloperKeyDecisionsDocsGenerator(Protocol):
    FLOW_DEVELOPER_KEY_DECISION_SLUGS: tuple[str, ...]
    FLOW_DEVELOPER_KEY_DECISIONS: tuple[_FlowDeveloperKeyDecision, ...]
    FlowDecisionSourceRef: _FlowDecisionSourceRefFactory
    FlowDeveloperKeyDecision: _FlowDeveloperKeyDecisionFactory

    def render_flow_developer_key_decisions_docs_page(self) -> str: ...

    def validate_flow_developer_key_decisions(
        self,
        decisions: Sequence[_FlowDeveloperKeyDecision] | None = None,
    ) -> None: ...


class _ReviewerGuideSourceRef(Protocol):
    label: str
    path: str


class _ReviewerChecklistTopic(Protocol):
    slug: str
    title: str
    check: str
    reject: str
    source_refs: tuple[_ReviewerGuideSourceRef, ...]


class _ReviewerProcedureStep(Protocol):
    title: str
    body: str


class _ReviewerRoute(Protocol):
    slug: str
    change_type: str
    start_here: str
    proof: str
    source_refs: tuple[_ReviewerGuideSourceRef, ...]
    procedure_title: str | None
    procedure_steps: tuple[_ReviewerProcedureStep, ...]


class _ReviewerValidationCommand(Protocol):
    slug: str
    label: str
    command: str
    workdir: str
    when_to_run: str
    referenced_paths: tuple[str, ...]
    requires_path_arguments: bool


class _ReviewerDebugRunbookStep(Protocol):
    slug: str
    inspect: str
    signals: tuple[str, ...]
    next_action: str
    source_refs: tuple[_ReviewerGuideSourceRef, ...]


class _ReviewerGuideSourceRefFactory(Protocol):
    def __call__(self, label: str, path: str) -> _ReviewerGuideSourceRef: ...


class _ReviewerChecklistTopicFactory(Protocol):
    def __call__(
        self,
        slug: str,
        title: str,
        check: str,
        reject: str,
        source_refs: tuple[_ReviewerGuideSourceRef, ...],
    ) -> _ReviewerChecklistTopic: ...


class _ReviewerProcedureStepFactory(Protocol):
    def __call__(self, title: str, body: str) -> _ReviewerProcedureStep: ...


class _ReviewerRouteFactory(Protocol):
    def __call__(
        self,
        slug: str,
        change_type: str,
        start_here: str,
        proof: str,
        source_refs: tuple[_ReviewerGuideSourceRef, ...],
        procedure_title: str | None = None,
        procedure_steps: tuple[_ReviewerProcedureStep, ...] = (),
    ) -> _ReviewerRoute: ...


class _ReviewerValidationCommandFactory(Protocol):
    def __call__(
        self,
        slug: str,
        label: str,
        command: str,
        workdir: str,
        when_to_run: str,
        referenced_paths: tuple[str, ...],
        requires_path_arguments: bool = True,
    ) -> _ReviewerValidationCommand: ...


class _ReviewerDebugRunbookStepFactory(Protocol):
    def __call__(
        self,
        slug: str,
        inspect: str,
        signals: tuple[str, ...],
        next_action: str,
        source_refs: tuple[_ReviewerGuideSourceRef, ...],
    ) -> _ReviewerDebugRunbookStep: ...


class _FlowDeveloperReviewerGuideDocsGenerator(Protocol):
    REVIEWER_CHECKLIST_TOPIC_SLUGS: tuple[str, ...]
    REVIEWER_ROUTE_SLUGS: tuple[str, ...]
    REVIEWER_VALIDATION_COMMAND_SLUGS: tuple[str, ...]
    REVIEWER_DEBUG_RUNBOOK_STEP_SLUGS: tuple[str, ...]
    REVIEWER_CHECKLIST_TOPICS: tuple[_ReviewerChecklistTopic, ...]
    REVIEWER_ROUTES: tuple[_ReviewerRoute, ...]
    REVIEWER_VALIDATION_COMMANDS: tuple[_ReviewerValidationCommand, ...]
    REVIEWER_DEBUG_RUNBOOK_STEPS: tuple[_ReviewerDebugRunbookStep, ...]
    ReviewerGuideSourceRef: _ReviewerGuideSourceRefFactory
    ReviewerChecklistTopic: _ReviewerChecklistTopicFactory
    ProcedureStep: _ReviewerProcedureStepFactory
    ReviewerRoute: _ReviewerRouteFactory
    ReviewerValidationCommand: _ReviewerValidationCommandFactory
    ReviewerDebugRunbookStep: _ReviewerDebugRunbookStepFactory

    def render_flow_developer_reviewer_guide_docs_page(self) -> str: ...

    def validate_reviewer_guide_catalog(
        self,
        topics: Sequence[_ReviewerChecklistTopic] | None = None,
        routes: Sequence[_ReviewerRoute] | None = None,
        commands: Sequence[_ReviewerValidationCommand] | None = None,
        runbook_steps: Sequence[_ReviewerDebugRunbookStep] | None = None,
    ) -> None: ...


class _FlowConsumerTestReceipt(Protocol):
    file_path: str
    function_name: str


class _FlowConsumerEndpointSequence(Protocol):
    slug: str
    title: str
    runtime_path_fields: tuple[str, ...]
    run_contract_fields: tuple[str, ...]
    endpoint_operation_ids: tuple[str, ...]
    receipts: tuple[_FlowConsumerTestReceipt, ...]
    error_codes: tuple[FlowApiErrorCode, ...]


class _FlowConsumerWorkedExampleHop(Protocol):
    title: str
    operation_id: str


class _FlowConsumerScenario(Protocol):
    slug: str
    title: str
    golden_ids: tuple[str, ...]


class _FlowConsumerCapabilityMatrixRow(Protocol):
    input_mode: str
    output_artifact: str
    output_types: tuple[str, ...]
    output_modes: tuple[str, ...]


class _FlowConsumerEndpointPitfallRow(Protocol):
    category: str
    capability: str
    operation_ids: tuple[str, ...]
    error_code: FlowApiErrorCode | None
    consumer_action: str | None


class _FlowConsumerUnsupportedCallout(Protocol):
    feature: str
    type: Literal["warning"]
    supported_alternative: str


class _FlowConsumerNavEntry(Protocol):
    slug: str
    title: str
    href: str
    job: str


class _FlowConsumerGuideDocsGenerator(Protocol):
    CONSUMER_GUIDE_PAGE_SLUG: str
    ENDPOINT_SEQUENCES: tuple[_FlowConsumerEndpointSequence, ...]
    WORKED_EXAMPLE_HOPS: tuple[_FlowConsumerWorkedExampleHop, ...]
    WORKED_EXAMPLE_CHECKPOINT: dict[str, object]
    WORKED_EXAMPLE_CHECKPOINT_EDIT_REQUEST: dict[str, object]
    WORKED_EXAMPLE_CHECKPOINT_EDITED_RESPONSE: dict[str, object]
    WORKED_EXAMPLE_CHECKPOINT_APPROVED_RESPONSE: dict[str, object]
    WORKED_EXAMPLE_CHECKPOINT_RESUME_RESPONSE: dict[str, object]
    WORKED_EXAMPLE_FINAL_STEP_RESULT: dict[str, object]
    WORKED_EXAMPLE_ARTIFACT_RESULT_FILE: dict[str, object]
    WORKED_EXAMPLE_SIGNED_URL_RESPONSE: dict[str, object]
    SCENARIOS: tuple[_FlowConsumerScenario, ...]
    CAPABILITY_MATRIX_ROWS: tuple[_FlowConsumerCapabilityMatrixRow, ...]
    ENDPOINT_PITFALL_ROWS: tuple[_FlowConsumerEndpointPitfallRow, ...]
    UNSUPPORTED_CALLOUTS: tuple[_FlowConsumerUnsupportedCallout, ...]
    CAPABILITY_MATRIX_ROW_BUDGET: int

    def render_flow_consumer_guide_page(self) -> str: ...

    def validate_flow_consumer_guide_catalog(self) -> None: ...


class _FlowConsumerSectionDocsGenerator(Protocol):
    FLOW_CONSUMER_SECTION_NAV: tuple[_FlowConsumerNavEntry, ...]

    def render_flow_consumer_section_index_page(self) -> str: ...

    def validate_flow_consumer_section_catalog(self) -> None: ...


class _FlowConsumerErrorCatalogRow(Protocol):
    category: str
    code: str
    handling_phase: str
    consumer_action: str


class _FlowConsumerErrorCatalogDocsGenerator(Protocol):
    def flow_consumer_error_catalog_rows(
        self,
    ) -> tuple[_FlowConsumerErrorCatalogRow, ...]: ...

    def render_flow_consumer_error_reference_page(self) -> str: ...


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _assert_generated_doc(actual: str, expected: str, *, path: Path) -> None:
    relative_path = path.relative_to(REPO_ROOT)
    assert actual == expected, (
        f"Generated Flow docs are stale at {relative_path}. "
        f"Run `{FLOW_DOCS_REGEN_COMMAND}` from the repository root."
    )


def _non_empty_lines(page: str) -> list[str]:
    return [line.strip() for line in page.splitlines() if line.strip()]


def _content_start_for(page: str) -> int:
    lines = _non_empty_lines(page)
    return 1 if lines and lines[0].startswith("import ") else 0


def _assert_purpose_header(page: str, expected_title: str) -> None:
    lines = _non_empty_lines(page)
    content_start = _content_start_for(page)
    assert lines[content_start] == f"# {expected_title}"
    purpose = lines[content_start + 1]
    assert not purpose.startswith("**Read this when")
    assert not purpose.startswith("**After reading you can")
    assert purpose.endswith(".")
    assert len(purpose) <= 360


def _section_after(page: str, heading: str) -> str:
    return page.split(heading, maxsplit=1)[1]


def _heading_section(page: str, heading: str) -> str:
    section = _section_after(page, heading)
    next_heading = re.search(r"\n## ", section)
    if next_heading is None:
        return section
    return section[: next_heading.start()]


def _flow_developer_meta_titles() -> dict[str, str]:
    meta = _read(FLOW_DEVELOPER_DOCS_META)
    return {
        match.group("quoted_slug") or match.group("bare_slug"): match.group("title")
        for match in FLOW_DEVELOPER_META_TITLE_PATTERN.finditer(meta)
    }


def _related_cards_from_page(page: str) -> tuple[tuple[str, str], ...]:
    return _nextra_cards_from_section(_heading_section(page, "## Related"))


def _nextra_cards_from_section(section: str) -> tuple[tuple[str, str], ...]:
    return tuple(
        (unescape(match.group("title")), unescape(match.group("href")))
        for match in FLOW_DOCS_RELATED_CARD_PATTERN.finditer(section)
    )


def _flow_developer_doc_for_href(href: str) -> tuple[str, Path]:
    prefix = "/docs/flows-for-developers/"
    assert href.startswith(prefix), href
    slug = href.removeprefix(prefix)
    assert slug
    assert "/" not in slug
    path = FLOW_DEVELOPER_DOCS_DIR / f"{slug}.mdx"
    assert path.is_file(), href
    return slug, path


def _json_documents(path: Path) -> list[object]:
    return [json.loads(block) for block in JSON_CODE_BLOCK_PATTERN.findall(_read(path))]


def _find_json_object(path: Path, *, required_keys: set[str]) -> dict[str, object]:
    matches = [
        cast(dict[str, object], document)
        for document in _json_documents(path)
        if isinstance(document, dict) and required_keys <= set(document)
    ]

    assert len(matches) == 1, f"Expected one JSON object with keys {required_keys}"
    return matches[0]


def _find_json_list(path: Path, *, required_keys: set[str]) -> list[object]:
    matches = [
        cast(list[object], document)
        for document in _json_documents(path)
        if isinstance(document, list)
        and document
        and isinstance(document[0], dict)
        and required_keys <= set(document[0])
    ]

    assert len(matches) == 1, f"Expected one JSON list with item keys {required_keys}"
    return matches[0]


def _assert_json_object_present(path: Path, expected: dict[str, object]) -> None:
    assert expected in [
        document for document in _json_documents(path) if isinstance(document, dict)
    ]


def _flow_error_code_table_values(path: Path) -> set[str]:
    candidates: set[str] = set()
    for line in _read(path).splitlines():
        if not line.startswith("|"):
            continue

        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 3 or all(set(cell) <= {"-", " "} for cell in cells):
            continue

        for cell in cells:
            for token in BACKTICKED_TOKEN_PATTERN.findall(cell):
                if token.startswith(("flow_", "typed_io_")):
                    candidates.add(token)

    return candidates


def _typescript_meta_key(slug: str) -> str:
    return slug if slug.isidentifier() else f'"{slug}"'


def _expected_next_line(slug: str, nav_entries: Sequence[_FlowConsumerNavEntry]) -> str:
    entries = list(nav_entries)
    slugs = [entry.slug for entry in entries]
    index = slugs.index(slug)
    next_entry = entries[index + 1]
    return f"Next: [{next_entry.title}]({next_entry.href})."


def _flow_run_create_request_example() -> dict[str, object]:
    json_schema_extra = FlowRunCreateRequest.model_config["json_schema_extra"]
    assert isinstance(json_schema_extra, dict)
    example = json_schema_extra["example"]
    assert isinstance(example, dict)
    return cast(dict[str, object], example)


def _signed_url_request_example() -> dict[str, object]:
    json_schema_extra = SignedURLRequest.model_config["json_schema_extra"]
    assert isinstance(json_schema_extra, dict)
    example = json_schema_extra["example"]
    assert isinstance(example, dict)
    return cast(dict[str, object], example)


def _load_flow_developer_architecture_docs_generator() -> (
    _FlowDeveloperArchitectureDocsGenerator
):
    spec = importlib.util.spec_from_file_location(
        "flow_developer_architecture_docs",
        FLOW_DEVELOPER_ARCHITECTURE_DOCS_GENERATOR,
    )
    if spec is None or spec.loader is None:
        pytest.fail(
            f"Could not load generator module from "
            f"{FLOW_DEVELOPER_ARCHITECTURE_DOCS_GENERATOR}"
        )

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast(_FlowDeveloperArchitectureDocsGenerator, module)


def _load_flow_developer_lifecycle_docs_generator() -> (
    _FlowDeveloperLifecycleDocsGenerator
):
    spec = importlib.util.spec_from_file_location(
        "flow_developer_lifecycle_docs",
        FLOW_DEVELOPER_LIFECYCLE_DOCS_GENERATOR,
    )
    if spec is None or spec.loader is None:
        pytest.fail(
            f"Could not load generator module from "
            f"{FLOW_DEVELOPER_LIFECYCLE_DOCS_GENERATOR}"
        )

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast(_FlowDeveloperLifecycleDocsGenerator, module)


def _load_flow_developer_key_decisions_docs_generator() -> (
    _FlowDeveloperKeyDecisionsDocsGenerator
):
    spec = importlib.util.spec_from_file_location(
        "flow_developer_key_decisions_docs",
        FLOW_DEVELOPER_KEY_DECISIONS_DOCS_GENERATOR,
    )
    if spec is None or spec.loader is None:
        pytest.fail(
            f"Could not load generator module from "
            f"{FLOW_DEVELOPER_KEY_DECISIONS_DOCS_GENERATOR}"
        )

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast(_FlowDeveloperKeyDecisionsDocsGenerator, module)


def _load_flow_developer_reviewer_guide_docs_generator() -> (
    _FlowDeveloperReviewerGuideDocsGenerator
):
    spec = importlib.util.spec_from_file_location(
        "flow_developer_reviewer_guide_docs",
        FLOW_DEVELOPER_REVIEWER_GUIDE_DOCS_GENERATOR,
    )
    if spec is None or spec.loader is None:
        pytest.fail(
            f"Could not load generator module from "
            f"{FLOW_DEVELOPER_REVIEWER_GUIDE_DOCS_GENERATOR}"
        )

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast(_FlowDeveloperReviewerGuideDocsGenerator, module)


def _load_flow_consumer_guide_docs_generator(
    module_name: str,
    module_path: Path,
) -> _FlowConsumerGuideDocsGenerator:
    scripts_dir = str(BACKEND_ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        pytest.fail(f"Could not load generator module from {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast(_FlowConsumerGuideDocsGenerator, module)


def _load_flow_consumer_guide_generators() -> dict[
    str, _FlowConsumerGuideDocsGenerator
]:
    return {
        "designing-flows": _load_flow_consumer_guide_docs_generator(
            "flow_consumer_designing_flows_docs",
            FLOW_CONSUMER_DESIGNING_GUIDE_DOCS_GENERATOR,
        ),
        "integrating-flows": _load_flow_consumer_guide_docs_generator(
            "flow_consumer_integrating_flows_docs",
            FLOW_CONSUMER_INTEGRATING_GUIDE_DOCS_GENERATOR,
        ),
        "flows-faq": _load_flow_consumer_guide_docs_generator(
            "flow_consumer_faq_docs",
            FLOW_CONSUMER_FAQ_GUIDE_DOCS_GENERATOR,
        ),
    }


def _load_flow_consumer_section_docs_generator() -> _FlowConsumerSectionDocsGenerator:
    scripts_dir = str(BACKEND_ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    spec = importlib.util.spec_from_file_location(
        "flow_consumer_section_docs",
        FLOW_CONSUMER_SECTION_DOCS_GENERATOR,
    )
    if spec is None or spec.loader is None:
        pytest.fail(
            f"Could not load generator module from {FLOW_CONSUMER_SECTION_DOCS_GENERATOR}"
        )

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast(_FlowConsumerSectionDocsGenerator, module)


def _load_flow_consumer_error_catalog_docs_generator() -> (
    _FlowConsumerErrorCatalogDocsGenerator
):
    scripts_dir = str(BACKEND_ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    spec = importlib.util.spec_from_file_location(
        "flow_consumer_error_catalog_docs",
        FLOW_CONSUMER_ERROR_CATALOG_DOCS_GENERATOR,
    )
    if spec is None or spec.loader is None:
        pytest.fail(
            f"Could not load generator module from "
            f"{FLOW_CONSUMER_ERROR_CATALOG_DOCS_GENERATOR}"
        )

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast(_FlowConsumerErrorCatalogDocsGenerator, module)


def _load_flow_docs_regen_generators() -> tuple[Callable[[], None], ...]:
    scripts_dir = str(BACKEND_ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    spec = importlib.util.spec_from_file_location(
        "generate_flow_docs",
        FLOW_DOCS_REGEN_SCRIPT,
    )
    if spec is None or spec.loader is None:
        pytest.fail(f"Could not load generator module from {FLOW_DOCS_REGEN_SCRIPT}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    generators = getattr(module, "FLOW_DOCS_GENERATORS")
    assert isinstance(generators, tuple)
    assert all(callable(generator) for generator in generators)
    return cast(tuple[Callable[[], None], ...], generators)


def _flow_runtime_public_field_names() -> set[str]:
    return set(FlowRuntimePathsPublic.model_fields) | {
        f"review_checkpoints.{field}"
        for field in FlowReviewCheckpointRuntimePathsPublic.model_fields
    }


def _flow_runtime_endpoint_field_names() -> set[str]:
    return (set(FlowRuntimePathsPublic.model_fields) - {"review_checkpoints"}) | {
        f"review_checkpoints.{field}"
        for field in FlowReviewCheckpointRuntimePathsPublic.model_fields
    }


def _flow_run_contract_public_field_names() -> set[str]:
    return (
        set(FlowRunContractPublic.model_fields)
        | {
            f"final_output.{field}"
            for field in FlowFinalOutputContractPublic.model_fields
        }
        | {f"form_fields.{field}" for field in FormFieldPublic.model_fields}
        | {
            f"steps_requiring_input.{field}"
            for field in FlowRuntimeInputContractPublic.model_fields
        }
        | {
            f"steps_requiring_review.{field}"
            for field in FlowReviewStepContractPublic.model_fields
        }
        | {
            f"runtime_upload_policy.{field}"
            for field in FlowRuntimeUploadPolicyPublic.model_fields
        }
    )


def _flow_runtime_endpoint_route_paths() -> set[str]:
    excluded_names = {"FLOW_ROOT_PATH"}
    return {
        value
        for name, value in vars(flow_runtime_path_constants).items()
        if name.endswith("_PATH")
        and name not in excluded_names
        and isinstance(value, str)
    }


def _flow_runtime_endpoint_contract_key(
    contract: FlowRuntimeEndpointContract,
) -> tuple[str, str]:
    return (contract.route_path, contract.method)


def _live_flow_runtime_route_contracts() -> dict[tuple[str, str], tuple[str, int]]:
    runtime_route_paths = _flow_runtime_endpoint_route_paths()
    live_routes: dict[tuple[str, str], tuple[str, int]] = {}

    for route in flatten_routes(list(flow_router.routes)):
        if not isinstance(route.route, APIRoute):
            continue
        if route.path not in runtime_route_paths:
            continue

        methods = sorted(route.methods - {"HEAD", "OPTIONS"})
        assert len(methods) == 1
        assert route.status_code is not None
        assert isinstance(route.status_code, int)

        method = methods[0].lower()
        route_key = (route.path, method)
        assert route_key not in live_routes
        live_routes[route_key] = (route.operation_id or "", route.status_code)

    return live_routes


def _assert_flow_runtime_endpoint_contracts_match_live_routes(
    contracts: tuple[FlowRuntimeEndpointContract, ...],
) -> None:
    registry_routes = {
        _flow_runtime_endpoint_contract_key(contract): contract
        for contract in contracts
    }
    assert len(registry_routes) == len(contracts)

    live_routes = _live_flow_runtime_route_contracts()
    assert set(registry_routes) == set(live_routes)

    for route_key, contract in registry_routes.items():
        operation_id, status_code = live_routes[route_key]
        assert contract.operation_id == operation_id
        assert contract.success_status == status_code


def _assert_flow_runtime_endpoint_fields_match_runtime_paths(
    contracts: tuple[FlowRuntimeEndpointContract, ...],
) -> None:
    projected_fields = [
        ".".join(projection.field_path)
        for contract in contracts
        for projection in contract.runtime_path_fields
    ]

    assert len(projected_fields) == len(set(projected_fields))
    assert set(projected_fields) == _flow_runtime_endpoint_field_names()


def test_flow_docs_regen_make_target_invokes_canonical_generator() -> None:
    result = subprocess.run(
        ["make", "-n", "docs:regen"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert (
        "cd backend && set -a && . .env.template && set +a "
        "&& uv run python scripts/generate_flow_docs.py"
    ) in result.stdout


def test_flow_docs_regen_is_wired_into_ci() -> None:
    workflow = _read(CI_WORKFLOW)

    assert "Check generated Flow docs" in workflow
    assert "make docs:regen" in workflow
    assert "git diff --exit-code" in workflow
    assert "frontend/apps/docs-site/src/content/docs/flows-for-developers" in workflow
    assert "frontend/apps/docs-site/src/content/guides/flows" in workflow


def test_flow_docs_regen_orchestrator_covers_every_docs_generator() -> None:
    generators = _load_flow_docs_regen_generators()

    expected_script_paths = set(
        (BACKEND_ROOT / "scripts").glob("generate_flow_*_docs.py")
    )
    registered_script_paths = {
        BACKEND_ROOT / "scripts" / f"{generator.__module__}.py"
        for generator in generators
    }

    assert registered_script_paths == expected_script_paths


def test_flow_developer_mermaid_blocks_use_shared_figure_surface() -> None:
    developer_docs_with_mermaid = tuple(
        path
        for path in sorted(FLOW_DEVELOPER_DOCS_DIR.glob("*.mdx"))
        if "```mermaid" in _read(path)
    )

    assert developer_docs_with_mermaid

    for path in developer_docs_with_mermaid:
        page = _read(path)
        mermaid_blocks = MERMAID_CODE_BLOCK_PATTERN.findall(page)
        assert mermaid_blocks, path
        assert "<style>" not in page, path
        assert "flow-developer-context" not in page, path
        assert "style={{" not in page, path
        assert page.count(FLOW_DOCS_MERMAID_FIGURE_CLASS) == len(mermaid_blocks), path
        for block in mermaid_blocks:
            first_line = next(
                (line.strip() for line in block.splitlines() if line.strip()),
                None,
            )
            assert first_line == FLOW_DOCS_MERMAID_INIT_DIRECTIVE, path


def test_flow_docs_mermaid_figure_surface_is_owned_by_docs_site_css() -> None:
    css = _read(DOCS_SITE_GLOBAL_CSS)
    helper = FLOW_DOCS_MERMAID_HELPER.read_text(encoding="utf-8")

    assert f".{FLOW_DOCS_MERMAID_FIGURE_CLASS}" in css
    for declaration in (
        "overflow-x: auto;",
        "background: #f8f6f0;",
        "border: 1px solid #d8ccbb;",
        "border-radius: 8px;",
        "padding: 1rem;",
        "margin: 1rem 0;",
        "color-scheme: light;",
    ):
        assert declaration in css
    assert "style={{" not in helper


def test_flow_docs_mermaid_surface_color_matches_theme_labels() -> None:
    css = _read(DOCS_SITE_GLOBAL_CSS)
    match = re.search(
        rf"\.{FLOW_DOCS_MERMAID_FIGURE_CLASS}\s*\{{.*?background:\s*(#[0-9a-fA-F]{{6}});",
        css,
        re.DOTALL,
    )
    assert match is not None

    surface_background = match.group(1)
    assert '"theme":' not in FLOW_DOCS_MERMAID_INIT_DIRECTIVE
    assert f'"background": "{surface_background}"' in FLOW_DOCS_MERMAID_INIT_DIRECTIVE
    assert (
        f'"edgeLabelBackground": "{surface_background}"'
        in FLOW_DOCS_MERMAID_INIT_DIRECTIVE
    )


def test_flow_docs_mermaid_fences_have_one_generator_owner() -> None:
    for path in FLOW_DOCS_MERMAID_GENERATOR_SOURCES:
        assert "```mermaid" not in path.read_text(encoding="utf-8"), path

    assert "```mermaid" in FLOW_DOCS_MERMAID_HELPER.read_text(encoding="utf-8")


def test_flow_docs_mermaid_helper_rejects_prebuilt_fences() -> None:
    with pytest.raises(ValueError, match="code fences"):
        render_flow_docs_mermaid_block("```mermaid")


def test_flow_developer_docs_orientation_contract() -> None:
    page = _read(FLOW_DEVELOPER_DOCS_INDEX)
    section_meta = _read(FLOW_DEVELOPER_DOCS_META)
    docs_meta = _read(FLOW_DOCS_META)

    developer_pages = sorted(FLOW_DEVELOPER_DOCS_DIR.glob("*.mdx"))
    non_empty_lines = [line.strip() for line in page.splitlines() if line.strip()]
    mermaid_blocks = MERMAID_CODE_BLOCK_PATTERN.findall(page)

    assert len(developer_pages) == 7
    assert 'index: "Flows in 5 minutes"' in section_meta
    assert '  flows: "Eneo Flows",' in docs_meta
    assert '"flows-for-developers": "Flows for Developers"' in docs_meta
    assert not FLOW_ACCESS_MODEL_SVG.exists()
    assert non_empty_lines[0] == "# Flows in 5 minutes"
    assert non_empty_lines[1].startswith("Start here when you need to review")
    assert "**Read this when" not in page
    assert "**After reading you can" not in page
    assert PLACEHOLDER_DOC_PATTERN.search(page) is None
    assert len(mermaid_blocks) == 1

    diagram = mermaid_blocks[0]
    for required_node in (
        "FastAPI Flow API",
        "Worker runtime",
        "PostgreSQL",
        "Files",
        "AI models",
        "Spaces",
        "Tenants",
        "SDK",
    ):
        assert required_node in diagram

    for layer in ("api", "application", "domain", "infrastructure", "runtime"):
        assert f"`{layer}`" in page

    assert "## Review path" in page
    assert "| First-read goal" in page
    for sibling_page in (
        FLOW_DEVELOPER_DOCS_HOW_BUILT,
        FLOW_DEVELOPER_DOCS_DATA_SCHEMA,
        FLOW_DEVELOPER_DOCS_RUN_LIFECYCLE,
        FLOW_DEVELOPER_DOCS_WHEN_THINGS_FAIL,
        FLOW_DEVELOPER_DOCS_KEY_DECISIONS,
        FLOW_DEVELOPER_DOCS_REVIEWER_GUIDE,
    ):
        assert sibling_page.is_file()
        href = (
            "/docs/flows-for-developers/"
            f"{sibling_page.relative_to(FLOW_DEVELOPER_DOCS_DIR).with_suffix('')}"
        )
        assert href in page

    assert "/guides/flows-api-guide" in page
    assert "/docs/flows-for-developers/reviewing-flows-code" in page
    assert "/docs/flows" in page
    assert "docs/flows/architecture.md" in page
    assert "terminalization handoff" in page
    assert "Terminal run-state writes live in `application`" in page
    assert "FlowRunTerminalizer" in page


def test_flow_developer_docs_data_schema_is_generated_from_backend_metadata() -> None:
    from eneo.flows.infrastructure.flow_schema_docs_exporter import (
        _AGGREGATE_DESCRIPTIONS,
        FLOW_SCHEMA_MODEL_REGISTRY,
        FlowSchemaAggregate,
        _aggregate_heading_href,
        _aggregate_map_edges,
        _aggregate_map_relationship_lines,
        render_flow_schema_docs_page,
    )

    page = _read(FLOW_DEVELOPER_DOCS_DATA_SCHEMA)
    section_meta = _read(FLOW_DEVELOPER_DOCS_META)

    assert '"data-schema": "The data schema"' in section_meta
    _assert_generated_doc(
        page,
        render_flow_schema_docs_page(),
        path=FLOW_DEVELOPER_DOCS_DATA_SCHEMA,
    )
    _assert_purpose_header(page, "The data schema")
    assert "make docs:regen" in page
    assert "## Related" in page
    assert "/docs/flows-for-developers/key-decisions" in page
    assert "/docs/flows-for-developers/reviewing-flows-code" in page
    assert 'import { Tabs } from "nextra/components";' not in page
    assert "## Aggregate map" in page
    assert "## Schema map" not in page
    assert (
        "Single-direction links point from the aggregate that owns the foreign key"
        in page
    )
    assert "## Aggregate entity relationship diagrams" in page
    assert page.index("## Aggregate map") < page.index(
        "## Aggregate entity relationship diagrams"
    )
    assert "### ERD shortcuts" in page
    assert page.index("## Aggregate map") < page.index("### ERD shortcuts")
    assert page.index("### ERD shortcuts") < page.index("### Tables by aggregate")
    assert page.index("### Tables by aggregate") < page.index(
        "## Aggregate entity relationship diagrams"
    )
    assert "## Entity relationship diagram" not in page
    assert "\n## Deferred adjacent tables\n" not in page
    assert "<Tabs items={[" not in page
    assert "<Tabs.Tab>" not in page
    assert page.count(FLOW_DOCS_MERMAID_FIGURE_CLASS) == (
        len(tuple(FlowSchemaAggregate)) + 1
    )
    for aggregate in FlowSchemaAggregate:
        assert f"### {aggregate.value}" in page

    aggregate_map = page.split("## Aggregate map", maxsplit=1)[1].split(
        "## Aggregate entity relationship diagrams",
        maxsplit=1,
    )[0]
    shortcut_section = page.split("### ERD shortcuts", maxsplit=1)[1].split(
        "### Tables by aggregate",
        maxsplit=1,
    )[0]
    shortcut_cards = _nextra_cards_from_section(shortcut_section)

    assert "erDiagram" in aggregate_map
    assert "flowchart LR" not in aggregate_map
    assert "run_execution }o--|| flow_definition : references" in aggregate_map
    assert "run_execution }o--o{ review_and_rerun : mutual_FKs" in aggregate_map
    assert "retention }o--|| run_execution" not in aggregate_map
    assert "retention }o--o{ run_execution" not in aggregate_map
    assert "<Cards num={3}>" in shortcut_section
    assert tuple(title for title, _ in shortcut_cards) == tuple(
        aggregate.value for aggregate in FlowSchemaAggregate
    )
    assert tuple(href for _, href in shortcut_cards) == tuple(
        _aggregate_heading_href(aggregate) for aggregate in FlowSchemaAggregate
    )

    aggregate_edges = _aggregate_map_edges(FLOW_SCHEMA_MODEL_REGISTRY)
    assert (
        FlowSchemaAggregate.RUN_EXECUTION,
        FlowSchemaAggregate.FLOW_DEFINITION,
    ) in aggregate_edges
    assert (
        FlowSchemaAggregate.REVIEW_AND_RERUN,
        FlowSchemaAggregate.RUN_EXECUTION,
    ) in aggregate_edges
    assert (
        FlowSchemaAggregate.RETENTION,
        FlowSchemaAggregate.RUN_EXECUTION,
    ) not in aggregate_edges
    aggregate_relationship_lines = _aggregate_map_relationship_lines(
        FLOW_SCHEMA_MODEL_REGISTRY
    )
    assert (
        "  run_execution }o--|| flow_definition : references"
        in aggregate_relationship_lines
    )
    assert (
        "  run_execution }o--o{ review_and_rerun : mutual_FKs"
        in aggregate_relationship_lines
    )

    for aggregate in FlowSchemaAggregate:
        assert aggregate.value in aggregate_map
        assert _AGGREGATE_DESCRIPTIONS[aggregate] in aggregate_map
        for entry in FLOW_SCHEMA_MODEL_REGISTRY:
            if entry.aggregate is aggregate:
                assert f"`{entry.model.__table__.name}`" in aggregate_map

    assert "flow_classification_retention_policies" in page
    for boundary_table in (
        "tenants",
        "spaces",
        "users",
        "files",
        "assistants",
        "service_principals",
        "api_keys_v2",
        "jobs",
        "security_classifications",
    ):
        assert f"{boundary_table} {{" in page
        assert (
            f'{boundary_table} {{\n    string boundary "external owner"\n  }}' in page
        )

    assert (
        "flow_classification_retention_policies }o--|| tenants : "
        '"tenant_id ondelete=CASCADE"'
    ) in page
    assert (
        "flow_classification_retention_policies |o--|| security_classifications : "
        '"security_classification_id, tenant_id ondelete=CASCADE"'
    ) in page
    assert 'flows }o--o| users : "created_by_user_id ondelete=SET NULL"' in page
    assert 'flows }o--o| users : "owner_user_id ondelete=SET NULL"' in page
    assert 'flow_package_imports }o--o| flows : "flow_id ondelete=CASCADE"' in page
    assert (
        'flow_step_dependencies }o--|| flow_steps : "child_step_id ondelete=CASCADE"'
        in page
    )
    assert (
        'flow_step_dependencies }o--|| flow_steps : "parent_step_id ondelete=CASCADE"'
        in page
    )
    assert 'flow_steps }o--|| assistants : "assistant_id ondelete=RESTRICT"' in page
    assert (
        'flows |o--o| flow_versions : "id, published_version ondelete=NO ACTION"'
        in page
    )
    assert (
        'flow_template_assets }o--|| files : "file_id, tenant_id ondelete=RESTRICT"'
        in page
    )
    assert (
        "flow_runtime_uploaded_files |o--|| files : "
        '"file_id, tenant_id ondelete=CASCADE"' in page
    )
    assert (
        "flow_run_step_result_files }o--|| files : "
        '"file_id, tenant_id ondelete=RESTRICT"' in page
    )
    assert (
        "builder_session_files }o--|| files : "
        '"file_id, tenant_id ondelete=CASCADE"' in page
    )
    assert (
        "builder_sessions |o--o| builder_plans : "
        '"latest_plan_id, id ondelete=NO ACTION"' in page
    )


def test_flow_schema_docs_registry_covers_flow_schema_models() -> None:
    from eneo.database.tables import (
        flow_classification_retention_policy_table,
        flow_tables,
    )
    from eneo.flows.infrastructure.flow_schema_docs_exporter import (
        FLOW_SCHEMA_MODEL_REGISTRY,
    )

    registry_table_names = [
        entry.model.__table__.name for entry in FLOW_SCHEMA_MODEL_REGISTRY
    ]
    assert len(registry_table_names) == len(set(registry_table_names))

    expected_table_names: set[str] = set()
    for module in (
        flow_tables,
        flow_classification_retention_policy_table,
    ):
        for model in vars(module).values():
            if getattr(model, "__module__", None) != module.__name__:
                continue
            table = getattr(model, "__table__", None)
            if isinstance(table, sa.Table):
                expected_table_names.add(table.name)

    assert set(registry_table_names) == expected_table_names


def test_flow_schema_docs_boundary_allowlist_covers_external_fks() -> None:
    from eneo.flows.infrastructure.flow_schema_docs_exporter import (
        FLOW_SCHEMA_BOUNDARY_TABLE_NAMES,
        FLOW_SCHEMA_MODEL_REGISTRY,
    )

    flow_table_names = {
        entry.model.__table__.name for entry in FLOW_SCHEMA_MODEL_REGISTRY
    }
    external_fk_targets = {
        constraint.referred_table.name
        for entry in FLOW_SCHEMA_MODEL_REGISTRY
        for constraint in entry.model.__table__.foreign_key_constraints
        if constraint.referred_table.name not in flow_table_names
    }

    assert external_fk_targets == FLOW_SCHEMA_BOUNDARY_TABLE_NAMES


def test_flow_schema_docs_relationship_labels_derive_fk_semantics() -> None:
    from eneo.flows.infrastructure.flow_schema_docs_exporter import (
        _flow_schema_relationship_from_constraint,
    )

    metadata = sa.MetaData()
    parent = sa.Table(
        "parent",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
    )
    required_child = sa.Table(
        "required_child",
        metadata,
        sa.Column("parent_id", sa.Integer, nullable=False),
        sa.ForeignKeyConstraint(["parent_id"], [parent.c.id], ondelete="CASCADE"),
    )
    nullable_child = sa.Table(
        "nullable_child",
        metadata,
        sa.Column("parent_id", sa.Integer, nullable=True),
        sa.ForeignKeyConstraint(["parent_id"], [parent.c.id]),
    )
    partial_unique_child = sa.Table(
        "partial_unique_child",
        metadata,
        sa.Column("parent_id", sa.Integer, nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["parent_id"], [parent.c.id], ondelete="RESTRICT"),
    )
    sa.Index(
        "uq_partial_unique_child_parent_active",
        partial_unique_child.c.parent_id,
        unique=True,
        postgresql_where=partial_unique_child.c.deleted_at.is_(None),
    )
    composite_parent = sa.Table(
        "composite_parent",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, primary_key=True),
    )
    composite_child = sa.Table(
        "composite_child",
        metadata,
        sa.Column("tenant_id", sa.Integer, nullable=False),
        sa.Column("parent_id", sa.Integer, nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "parent_id"),
        sa.ForeignKeyConstraint(
            ["parent_id", "tenant_id"],
            [composite_parent.c.id, composite_parent.c.tenant_id],
            ondelete="SET NULL",
        ),
    )
    subset_unique_child = sa.Table(
        "subset_unique_child",
        metadata,
        sa.Column("parent_id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, nullable=False),
        sa.ForeignKeyConstraint(
            ["parent_id", "tenant_id"],
            [composite_parent.c.id, composite_parent.c.tenant_id],
        ),
    )

    required_relationship = _flow_schema_relationship_from_constraint(
        next(iter(required_child.foreign_key_constraints))
    )
    assert required_relationship.source_cardinality == "}o"
    assert required_relationship.target_cardinality == "||"
    assert required_relationship.label == "parent_id ondelete=CASCADE"

    nullable_relationship = _flow_schema_relationship_from_constraint(
        next(iter(nullable_child.foreign_key_constraints))
    )
    assert nullable_relationship.target_cardinality == "o|"
    assert nullable_relationship.label == "parent_id ondelete=NO ACTION"

    partial_unique_relationship = _flow_schema_relationship_from_constraint(
        next(iter(partial_unique_child.foreign_key_constraints))
    )
    assert partial_unique_relationship.source_cardinality == "}o"
    assert partial_unique_relationship.target_cardinality == "||"
    assert partial_unique_relationship.label == "parent_id ondelete=RESTRICT"

    composite_relationship = _flow_schema_relationship_from_constraint(
        next(iter(composite_child.foreign_key_constraints))
    )
    assert composite_relationship.source_cardinality == "|o"
    assert composite_relationship.target_cardinality == "||"
    assert composite_relationship.label == "parent_id, tenant_id ondelete=SET NULL"

    subset_unique_relationship = _flow_schema_relationship_from_constraint(
        next(iter(subset_unique_child.foreign_key_constraints))
    )
    assert subset_unique_relationship.source_cardinality == "|o"


def test_flow_docs_nextra_card_renderers_validate_link_scope() -> None:
    from eneo.flows.infrastructure.flow_docs_related_cards import (
        FlowDocsNextraCard,
        render_flow_docs_anchor_shortcut_cards,
        render_flow_docs_related_nextra_cards,
    )

    assert render_flow_docs_anchor_shortcut_cards(
        (
            FlowDocsNextraCard("First", "#first"),
            FlowDocsNextraCard("Second", "#second"),
        )
    ) == render_flow_docs_related_nextra_cards(
        (
            FlowDocsNextraCard("First", "/first"),
            FlowDocsNextraCard("Second", "/second"),
        )
    ).replace('href="/first"', 'href="#first"').replace(
        'href="/second"', 'href="#second"'
    )

    with pytest.raises(ValueError, match="site-absolute"):
        render_flow_docs_related_nextra_cards((FlowDocsNextraCard("First", "#first"),))

    with pytest.raises(ValueError, match="anchor"):
        render_flow_docs_anchor_shortcut_cards((FlowDocsNextraCard("First", "/first"),))

    with pytest.raises(ValueError, match="unique"):
        render_flow_docs_anchor_shortcut_cards(
            (
                FlowDocsNextraCard("First", "#same"),
                FlowDocsNextraCard("Second", "#same"),
            )
        )


def test_flow_developer_docs_how_built_is_generated_from_layout_sources() -> None:
    from eneo.flows.infrastructure.flow_docs_related_cards import (
        FLOW_DOCS_RELATED_NEXTRA_CARDS_IMPORT,
        FlowDocsRelatedNextraCard,
        render_flow_docs_related_nextra_cards,
    )

    generator = _load_flow_developer_architecture_docs_generator()
    reviewer_generator = _load_flow_developer_reviewer_guide_docs_generator()

    page = _read(FLOW_DEVELOPER_DOCS_HOW_BUILT)
    section_meta = _read(FLOW_DEVELOPER_DOCS_META)

    assert '"how-built": "How Flows is built"' in section_meta
    _assert_generated_doc(
        page,
        generator.render_flow_developer_architecture_docs_page(),
        path=FLOW_DEVELOPER_DOCS_HOW_BUILT,
    )
    _assert_purpose_header(page, "How Flows is built")
    assert "This page is for" not in _non_empty_lines(page)[1]
    assert "## Change index" in page
    assert page.index("## Change index") < page.index("## Module ownership")
    assert (
        "[Reviewing Flows code](/docs/flows-for-developers/reviewing-flows-code)"
        in page
    )
    for route in reviewer_generator.REVIEWER_ROUTES:
        assert route.change_type in page
    first_diagram = MERMAID_CODE_BLOCK_PATTERN.findall(page)[0]
    assert "\\n" not in first_diagram
    assert "<br/>" in first_diagram
    assert '-. "must not import" .->' not in first_diagram
    assert (
        'engine["Flow engine"] -.->|must not import| builder["Flow AI Builder plugin"]'
        in first_diagram
    )
    assert "## Related" in page
    assert "/docs/flows-for-developers/run-lifecycle" in page
    assert _non_empty_lines(page)[0] == FLOW_DOCS_RELATED_NEXTRA_CARDS_IMPORT
    assert "target ownership model" in page
    assert "current root entry and its target-home group" in page
    assert "`FlowRunAccessPolicy`" in page
    assert "`tenant_id`" in page
    assert "`flow_run_access_denied`" in page
    assert "`auth_layer`" in page
    assert "## AI Builder create compile spine" in page
    assert "`FlowAssemblyPlan` owns topology" in page
    assert "`lower_assembly_plan`" in page
    assert "`architecture_materialization_failed`" in page
    assert "AI Builder create compile shape" in page
    assert page.index("## AI Builder create compile spine") < page.index(
        "## Change index"
    )

    change_index_section = page.split("## Change index", maxsplit=1)[1].split(
        "## Module ownership",
        maxsplit=1,
    )[0]
    module_ownership_section = page.split(
        "## Module ownership",
        maxsplit=1,
    )[1].split("## Source guards", maxsplit=1)[0]
    related_cards = (
        FlowDocsRelatedNextraCard(
            "The run lifecycle",
            "/docs/flows-for-developers/run-lifecycle",
        ),
        FlowDocsRelatedNextraCard(
            "Reviewing Flows code",
            "/docs/flows-for-developers/reviewing-flows-code",
        ),
    )
    related_section = _section_after(page, "## Related")
    layout_rows = tuple(
        sorted(
            generator.parse_package_layout_decision_table().values(),
            key=lambda row: (row.target_home, row.kind, row.entry),
        )
    )
    target_home_counts = {
        target_home: sum(1 for row in layout_rows if row.target_home == target_home)
        for target_home in sorted({row.target_home for row in layout_rows})
    }

    assert "<details>" not in change_index_section
    assert module_ownership_section.count("<details>") == len(target_home_counts)
    assert module_ownership_section.count("</details>") == len(target_home_counts)
    assert "| Target home" not in module_ownership_section
    for target_home, row_count in target_home_counts.items():
        assert (
            f"<summary><code>{target_home}</code> ({row_count} entries)</summary>"
            in module_ownership_section
        )
    for row in layout_rows:
        assert f"`{row.entry}`" in module_ownership_section
    assert related_section.strip() == render_flow_docs_related_nextra_cards(
        related_cards
    )
    assert "<Cards num={2}>" in related_section
    assert related_section.count("<Cards.Card") == len(related_cards)
    assert "\n- [" not in related_section


def test_flow_developer_docs_run_lifecycle_is_generated_from_lifecycle_sources() -> (
    None
):
    generator = _load_flow_developer_lifecycle_docs_generator()

    page = _read(FLOW_DEVELOPER_DOCS_RUN_LIFECYCLE)
    section_meta = _read(FLOW_DEVELOPER_DOCS_META)

    assert '"run-lifecycle": "The run lifecycle"' in section_meta
    _assert_generated_doc(
        page,
        generator.render_flow_developer_lifecycle_docs_page(),
        path=FLOW_DEVELOPER_DOCS_RUN_LIFECYCLE,
    )
    _assert_purpose_header(page, "The run lifecycle")
    assert "This page is for" not in _non_empty_lines(page)[1]
    assert "## Related" in page
    assert "/docs/flows-for-developers/key-decisions" in page
    assert "/docs/flows-for-developers/when-things-fail" in page

    for status in FlowRunStatus:
        assert f"`{status.value}`" in page
    for status in FLOW_RUN_STATUS_CAPABILITIES:
        assert f"`{status.value}`" in page
    for state in FlowRunReviewCheckpointState:
        assert f"`{state.value}`" in page
    for status in FlowRunRerunOperationStatus:
        assert f"`{status.value}`" in page
    for status in FlowStepResultStatus:
        assert f"`{status.value}`" in page
    for status in FlowStepAttemptStatus:
        assert f"`{status.value}`" in page
    assert "Rerun eligible" in page
    assert "Run capability meanings" in page
    assert "run occupies active execution capacity while queued or running" in page
    assert "stale queued runs may be claimed and dispatched again" in page
    assert "the rerun API can accept a completed or failed run" in page
    assert "Step failure and runtime file binding" in page
    assert "_handle_typed_step_failure" in page
    assert "_handle_generic_step_failure" in page
    assert "FlowRunTerminalizer" in page
    assert "pending --> failed: failed run terminalization" in page
    assert "active `pending` or `running` step results and open attempts as failed" in (
        page
    )
    assert "mark_running_if_claimable" in page
    assert "Flow dispatch coordinator" in page
    assert "application/flow_dispatch.py" in page
    assert "publish revisioned task" in page
    assert "Broker delivery remains at-least-once" in page
    assert "bounded recovery clock stays armed" in page
    assert "runtime/flow_runtime_health.py" in page
    assert "without lifecycle writes" in page
    assert "FlowReviewExpiryReconciler" in page
    assert "flows.reconcile_review_expiry" in page
    assert "flow_runtime_uploaded_files" in page
    assert "flow_run_step_input_files" in page
    assert "step_inputs[step_id].file_ids" in page
    assert "lock_for_binding=True" in page
    assert (
        "terminal checkpoint decision; run is cancelled with `flow_review_rejected`"
        in page
    )
    assert "checkpoint can still receive a decision" in page
    assert re.search(r"\| State\s+\| Open\s+\| Expires\s+\| Meaning", page)
    assert "run is failed by review rejection" not in page
    assert "awaiting_review --> cancelled: review rejected" in page


def test_flow_developer_docs_run_lifecycle_source_references_exist() -> None:
    page = _read(FLOW_DEVELOPER_DOCS_RUN_LIFECYCLE)
    referenced_files = sorted(set(BACKEND_SOURCE_FILE_REF_PATTERN.findall(page)))

    assert referenced_files
    missing_files = [
        file_ref
        for file_ref in referenced_files
        if not (REPO_ROOT / file_ref).is_file()
    ]

    assert missing_files == []


def test_flow_developer_lifecycle_docs_rejects_incomplete_step_state_notes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = _load_flow_developer_lifecycle_docs_generator()

    result_notes = dict(generator.STEP_RESULT_STATUS_NOTES)
    result_notes.pop(FlowStepResultStatus.FAILED)
    monkeypatch.setattr(generator, "STEP_RESULT_STATUS_NOTES", result_notes)

    with pytest.raises(ValueError, match="step result statuses"):
        generator._require_complete_state_notes()

    generator = _load_flow_developer_lifecycle_docs_generator()
    attempt_notes = dict(generator.STEP_ATTEMPT_STATUS_NOTES)
    attempt_notes.pop(FlowStepAttemptStatus.FAILED)
    monkeypatch.setattr(generator, "STEP_ATTEMPT_STATUS_NOTES", attempt_notes)

    with pytest.raises(ValueError, match="step attempt statuses"):
        generator._require_complete_state_notes()


def test_flow_developer_docs_when_things_fail_is_generated_from_error_taxonomy() -> (
    None
):
    page = _read(FLOW_DEVELOPER_DOCS_WHEN_THINGS_FAIL)
    section_meta = _read(FLOW_DEVELOPER_DOCS_META)
    mermaid_blocks = MERMAID_CODE_BLOCK_PATTERN.findall(page)

    assert '"when-things-fail": "When things fail"' in section_meta
    _assert_generated_doc(
        page,
        render_flow_error_taxonomy_docs_page(),
        path=FLOW_DEVELOPER_DOCS_WHEN_THINGS_FAIL,
    )
    _assert_purpose_header(page, "When things fail")
    assert "This page is for" not in _non_empty_lines(page)[1]
    assert "make docs:regen" in page
    assert "## Failure triage" in page
    assert page.index("## Failure triage") < page.index("## Failure taxonomy")
    assert "Step failed during execution" in page
    assert "## Related" in page
    assert "/docs/flows-for-developers/run-lifecycle" in page
    assert "/docs/flows-for-developers/key-decisions" in page
    assert PLACEHOLDER_DOC_PATTERN.search(page) is None
    assert len(mermaid_blocks) == 1

    diagram = mermaid_blocks[0]
    for required_node in (
        "Flow API",
        "FlowApiErrorCode",
        "SDK",
        "Frontend messages",
        "Run error payload",
        "Developer action",
    ):
        assert required_node in diagram

    for code in FlowApiErrorCode:
        assert f"`{code.value}`" in page
    assert "`run.error.code`" in page
    assert "`flow_error_<code>`" in page
    assert "/guides/flows-api-guide" in page

    triage_section = page.split("## Failure triage", maxsplit=1)[1].split(
        "## Failure taxonomy",
        maxsplit=1,
    )[0]
    taxonomy_section = page.split("## Failure taxonomy", maxsplit=1)[1].split(
        "## Source guards",
        maxsplit=1,
    )[0]
    category_counts = {
        category: sum(
            1 for entry in FLOW_ERROR_TAXONOMY.values() if entry.category == category
        )
        for category in FLOW_ERROR_CATEGORY_ORDER
        if any(entry.category == category for entry in FLOW_ERROR_TAXONOMY.values())
    }

    assert "<details>" not in triage_section
    assert taxonomy_section.count("<details>") == len(category_counts)
    assert taxonomy_section.count("</details>") == len(category_counts)
    for category, code_count in category_counts.items():
        assert f"### {category}" in taxonomy_section
        assert f"<summary>{code_count} error codes</summary>" in taxonomy_section


def test_flow_error_taxonomy_covers_error_catalog_and_frontend_messages() -> None:
    validate_flow_error_taxonomy()
    messages = json.loads(_read(FRONTEND_EN_MESSAGES))

    assert set(FLOW_ERROR_TAXONOMY) == set(FlowApiErrorCode)
    missing_message_keys = sorted(
        f"flow_error_{code.value}"
        for code in FlowApiErrorCode
        if f"flow_error_{code.value}" not in messages
    )
    assert missing_message_keys == []

    for code in FLOW_TYPED_IO_ERROR_CODES:
        assert FLOW_ERROR_TAXONOMY[code].category == "Typed input/output"
    for code in FLOW_RUN_TERMINAL_ERROR_CODES:
        assert "run error payload" in FLOW_ERROR_TAXONOMY[code].surfaced_through.lower()
    for code, entry in FLOW_ERROR_TAXONOMY.items():
        if "run error payload" in entry.surfaced_through.lower():
            assert code in FLOW_RUN_TERMINAL_ERROR_CODES


def test_published_definition_parser_errors_document_request_and_run_surfaces() -> None:
    dual_surface_codes = {
        FlowApiErrorCode.DEFINITION_CHECKSUM_MISMATCH,
        FlowApiErrorCode.DEFINITION_SCHEMA_VERSION_MISSING,
        FlowApiErrorCode.DEFINITION_SCHEMA_VERSION_UNSUPPORTED,
        FlowApiErrorCode.DEFINITION_FLOW_ID_INVALID,
        FlowApiErrorCode.DEFINITION_STEPS_INVALID,
        FlowApiErrorCode.INPUT_CONTRACT_INAPPLICABLE,
        FlowApiErrorCode.REVIEW_POLICY_INVALID,
    }
    consumer_rows = {
        FlowApiErrorCode(row.code): row
        for row in _load_flow_consumer_error_catalog_docs_generator().flow_consumer_error_catalog_rows()
    }

    for code in dual_surface_codes:
        entry = FLOW_ERROR_TAXONOMY[code]
        assert entry.surfaced_through == "API response and run error payload"
        assert entry.handling_phase == "Request path or run execution"
        assert consumer_rows[code].handling_phase == "Request path or run execution"

    request_only = FLOW_ERROR_TAXONOMY[FlowApiErrorCode.PUBLISHED_FORM_SCHEMA_INVALID]
    assert request_only.surfaced_through == "API error response"
    assert request_only.handling_phase == "Request path"

    for code in (
        FlowApiErrorCode.DEFINITION_INVALID,
        FlowApiErrorCode.DEFINITION_NO_EXECUTABLE_STEPS,
    ):
        run_only = FLOW_ERROR_TAXONOMY[code]
        assert run_only.surfaced_through == "Run error payload"
        assert run_only.handling_phase == "Run execution"


def test_flow_error_taxonomy_handling_phase_is_derived_from_surface() -> None:
    cases: dict[FlowErrorSurface, str] = {
        "API error response": "Request path",
        "Run error payload": "Run execution",
        "API response and run error payload": "Request path or run execution",
    }

    for surface, expected_phase in cases.items():
        entry = FlowErrorTaxonomyEntry(
            category="Flow access",
            surfaced_through=surface,
            cause="The caller used a runtime action before publication.",
            consumer_action="Publish the flow before retrying.",
            user_action="Publish the flow and try again.",
        )
        assert entry.handling_phase == expected_phase

    unknown_surface_entry = FlowErrorTaxonomyEntry(
        category="Flow access",
        surfaced_through=cast(FlowErrorSurface, "New surface"),
        cause="The caller used a runtime action before publication.",
        consumer_action="Publish the flow before retrying.",
        user_action="Publish the flow and try again.",
    )
    with pytest.raises(AssertionError):
        _ = unknown_surface_entry.handling_phase


def test_flow_error_taxonomy_rejects_incomplete_or_noisy_entries() -> None:
    incomplete = dict(FLOW_ERROR_TAXONOMY)
    incomplete.pop(FlowApiErrorCode.FLOW_NOT_PUBLISHED)
    with pytest.raises(ValueError, match="missing"):
        validate_flow_error_taxonomy(incomplete)

    noisy = dict(FLOW_ERROR_TAXONOMY)
    current = noisy[FlowApiErrorCode.FLOW_NOT_PUBLISHED]
    noisy[FlowApiErrorCode.FLOW_NOT_PUBLISHED] = replace(
        current,
        cause="Flow is unpublished. This second sentence would make the docs table harder to scan.",
    )
    with pytest.raises(ValueError, match="one sentence"):
        validate_flow_error_taxonomy(noisy)


def test_flow_developer_docs_key_decisions_is_generated_from_decision_catalog() -> None:
    generator = _load_flow_developer_key_decisions_docs_generator()

    page = _read(FLOW_DEVELOPER_DOCS_KEY_DECISIONS)
    section_meta = _read(FLOW_DEVELOPER_DOCS_META)
    mermaid_blocks = MERMAID_CODE_BLOCK_PATTERN.findall(page)

    assert '"key-decisions": "Key decisions"' in section_meta
    _assert_generated_doc(
        page,
        generator.render_flow_developer_key_decisions_docs_page(),
        path=FLOW_DEVELOPER_DOCS_KEY_DECISIONS,
    )
    _assert_purpose_header(page, "Key decisions")
    assert "This page is for" not in _non_empty_lines(page)[1]
    assert "## Related" in page
    assert "/docs/flows-for-developers/data-schema" in page
    assert "/docs/flows-for-developers/when-things-fail" in page
    assert "curated reviewer view" in page
    assert PLACEHOLDER_DOC_PATTERN.search(page) is None
    assert len(mermaid_blocks) == 1
    assert len(generator.FLOW_DEVELOPER_KEY_DECISIONS) == 11
    assert "cross-principal denial tests" in page
    assert "`FlowAssemblyPlan`" in page

    for slug in generator.FLOW_DEVELOPER_KEY_DECISION_SLUGS:
        assert any(
            decision.slug == slug for decision in generator.FLOW_DEVELOPER_KEY_DECISIONS
        )


def test_flow_developer_docs_key_decisions_source_references_exist() -> None:
    page = _read(FLOW_DEVELOPER_DOCS_KEY_DECISIONS)
    referenced_files = sorted(set(FLOW_DEVELOPER_SOURCE_FILE_REF_PATTERN.findall(page)))

    assert "backend/.importlinter" in referenced_files
    assert "docs/flows/package-layout.md" in referenced_files
    assert referenced_files
    assert all(":" not in file_ref for file_ref in referenced_files)
    missing_files = [
        file_ref
        for file_ref in referenced_files
        if not (REPO_ROOT / file_ref).is_file()
    ]

    assert missing_files == []


def test_flow_developer_key_decision_catalog_rejects_drift() -> None:
    generator = _load_flow_developer_key_decisions_docs_generator()
    decisions = generator.FLOW_DEVELOPER_KEY_DECISIONS
    first = decisions[0]
    first_source = first.source_refs[0]

    duplicate_slug = generator.FlowDeveloperKeyDecision(
        decisions[1].slug,
        first.title,
        first.context,
        first.decision,
        first.consequences,
        first.source_refs,
    )
    with pytest.raises(ValueError, match="duplicate slugs"):
        generator.validate_flow_developer_key_decisions(
            (duplicate_slug, *decisions[1:])
        )

    missing_source = generator.FlowDeveloperKeyDecision(
        first.slug,
        first.title,
        first.context,
        first.decision,
        first.consequences,
        (
            generator.FlowDecisionSourceRef(
                first_source.label,
                "backend/src/eneo/flows/does_not_exist.py",
            ),
        ),
    )
    with pytest.raises(ValueError, match="source file does not exist"):
        generator.validate_flow_developer_key_decisions(
            (missing_source, *decisions[1:])
        )

    over_budget = generator.FlowDeveloperKeyDecision(
        first.slug,
        first.title,
        "This context is intentionally long so the generated key decisions page cannot grow into verbose architecture prose that repeats the refactor journal instead of giving a reviewer a bounded decision summary with one direct sentence and a clear operational review boundary.",
        first.decision,
        first.consequences,
        first.source_refs,
    )
    with pytest.raises(ValueError, match="one short sentence"):
        generator.validate_flow_developer_key_decisions((over_budget, *decisions[1:]))

    with pytest.raises(ValueError, match="exactly 11 decisions"):
        generator.validate_flow_developer_key_decisions(decisions[:-1])


def test_flow_developer_docs_reviewer_guide_is_generated_from_review_catalog() -> None:
    from eneo.flows.infrastructure.flow_docs_related_cards import (
        FlowDocsRelatedNextraCard,
        render_flow_docs_related_nextra_cards,
    )

    generator = _load_flow_developer_reviewer_guide_docs_generator()

    page = _read(FLOW_DEVELOPER_DOCS_REVIEWER_GUIDE)
    section_meta = _read(FLOW_DEVELOPER_DOCS_META)
    mermaid_blocks = MERMAID_CODE_BLOCK_PATTERN.findall(page)

    assert '"reviewing-flows-code": "Reviewing Flows code"' in section_meta
    _assert_generated_doc(
        page,
        generator.render_flow_developer_reviewer_guide_docs_page(),
        path=FLOW_DEVELOPER_DOCS_REVIEWER_GUIDE,
    )
    _assert_purpose_header(page, "Reviewing Flows code")
    assert "This page is for" not in _non_empty_lines(page)[1]
    assert "## Common changes" in page
    assert "Add a step capability" in page
    assert "Add an error code" in page
    assert "Change a run state" in page
    assert "Add a JSONB field" in page
    assert "make docs:regen" in page
    assert "## Related" in page
    assert "/docs/flows-for-developers/how-built" in page
    assert "/docs/flows-for-developers/data-schema" in page
    assert 'import { Cards, Steps } from "nextra/components";' in page
    assert PLACEHOLDER_DOC_PATTERN.search(page) is None
    assert len(mermaid_blocks) == 1

    diagram = mermaid_blocks[0]
    for required_node in (
        "Flow PR",
        "API/router",
        "Runtime/executor",
        "Step handler",
        "Runtime file/upload",
        "Schema/migration",
        "Error-code",
        "Review checkpoint",
        "Docs",
        "Validation",
    ):
        assert required_node in diagram

    assert generator.REVIEWER_CHECKLIST_TOPIC_SLUGS == (
        "single-owner",
        "typed-errors",
        "tenant-principal-scope",
        "behavior-tests",
        "no-legacy",
        "docs-parity",
        "api-consumer",
        "observability",
    )
    assert generator.REVIEWER_ROUTE_SLUGS == (
        "api-router",
        "runtime-executor",
        "step-handler",
        "runtime-file-upload",
        "schema-migration",
        "error-code",
        "review-checkpoint",
        "docs",
    )
    assert generator.REVIEWER_VALIDATION_COMMAND_SLUGS == (
        "docs-regen",
        "docs-contract",
        "ruff",
        "pyright",
        "docs-prettier",
        "targeted-pytest",
        "import-boundary",
    )
    routes_with_procedures = tuple(
        route for route in generator.REVIEWER_ROUTES if route.procedure_title
    )
    assert tuple(route.slug for route in routes_with_procedures) == (
        "runtime-executor",
        "step-handler",
        "schema-migration",
        "error-code",
    )
    assert tuple(route.procedure_title for route in routes_with_procedures) == (
        "Change a run state",
        "Add a step capability",
        "Add a JSONB field",
        "Add an error code",
    )
    common_changes = page.split("## Common changes", maxsplit=1)[1].split(
        "## Review checklist",
        maxsplit=1,
    )[0]
    assert page.count("<Steps>") == len(routes_with_procedures)
    assert page.count("</Steps>") == len(routes_with_procedures)
    assert common_changes.count("<Steps>") == len(routes_with_procedures)
    assert common_changes.count("</Steps>") == len(routes_with_procedures)
    assert re.search(r"(?m)^\d+\. ", common_changes) is None
    assert generator.REVIEWER_DEBUG_RUNBOOK_STEP_SLUGS == (
        "start-from-run-contract",
        "queued-without-worker-span",
        "run-span-correlation",
        "step-span-correlation",
        "terminalization-event",
        "persisted-state-owner",
        "consumer-facing-error",
    )
    for topic in generator.REVIEWER_CHECKLIST_TOPICS:
        assert topic.title in page
        assert topic.check in page
        assert topic.reject in page
    for route in generator.REVIEWER_ROUTES:
        assert route.change_type in page
        assert route.start_here in page
        assert route.proof in page
        if route.procedure_title:
            assert route.procedure_title in page
            assert len(route.procedure_steps) >= 3
            recipe_block = common_changes.split(
                f"### {route.procedure_title}",
                maxsplit=1,
            )[1]
            next_recipe = re.search(r"(?m)^### ", recipe_block)
            if next_recipe is not None:
                recipe_block = recipe_block[: next_recipe.start()]
            assert recipe_block.startswith("\n\n<Steps>\n\n")
            steps_block = recipe_block.split("<Steps>", maxsplit=1)[1].split(
                "</Steps>",
                maxsplit=1,
            )[0]
            assert re.search(r"(?m)^### ", steps_block) is None
            assert re.search(r"(?m)^#### ", steps_block) is None
            assert recipe_block.rstrip().endswith("</Steps>")
            for step in route.procedure_steps:
                assert f"<h4>{step.title}</h4>" in steps_block
                assert step.body in steps_block
                assert "`" not in step.title
                assert "|" not in step.title
                assert "\n" not in step.title
                assert step.title != step.body
            assert f"### {route.procedure_title}\n\n<Steps>" in common_changes
    validation_section = page.split("## Validation commands", maxsplit=1)[1]
    assert "<Steps>" not in validation_section
    related_cards = (
        FlowDocsRelatedNextraCard(
            "How Flows is built",
            "/docs/flows-for-developers/how-built",
        ),
        FlowDocsRelatedNextraCard(
            "The data schema",
            "/docs/flows-for-developers/data-schema",
        ),
    )
    related_section = _section_after(page, "## Related")
    assert related_section.strip() == render_flow_docs_related_nextra_cards(
        related_cards
    )
    assert "<Cards num={2}>" in related_section
    assert related_section.count("<Cards.Card") == len(related_cards)
    assert "\n- [" not in related_section
    assert "STEP_HANDLER_REGISTRY" not in page
    assert "FlowRunExecutor._build_step_handler" in page
    assert "runtime/step_handlers/" in page
    assert "output_modes.py" in page
    assert "output_processing.py" in page
    assert "runtime/step_definition_parser.py" in page
    assert "Runtime file or upload binding" in page
    assert "FlowRuntimeFileService" in page
    assert "flow_runtime_file_service.py" in page
    assert "flow_runtime_upload_repo.py" in page
    assert "lock_for_binding" in page
    assert "Tenant filters" in page
    assert "cross-principal denial tests" in page
    for command in generator.REVIEWER_VALIDATION_COMMANDS:
        assert command.label in page
        assert command.command in page
        assert f"`{command.workdir}`" in page
        assert "::" not in command.command
    assert "## Debugging a stuck run" in page
    assert "worker-root signals" in page
    for step in generator.REVIEWER_DEBUG_RUNBOOK_STEPS:
        assert step.inspect in page
        assert step.next_action in page
        for signal in step.signals:
            assert f"`{signal}`" in page

    rendered_signals = {
        signal
        for step in generator.REVIEWER_DEBUG_RUNBOOK_STEPS
        for signal in step.signals
    }
    assert FLOW_RUN_EXECUTE_SPAN_NAME in rendered_signals
    assert FLOW_STEP_EXECUTE_SPAN_NAME in rendered_signals
    assert FLOW_RUN_LIFECYCLE_LOG_MESSAGE in rendered_signals
    assert FLOW_RUN_LIFECYCLE_EVENT_NAME in rendered_signals
    assert FLOW_RUN_TERMINALIZATION_OPERATION in rendered_signals
    assert FLOW_RUN_SPAN_ATTRIBUTE_KEYS <= rendered_signals
    assert FLOW_STEP_SPAN_ATTRIBUTE_KEYS <= rendered_signals
    assert "FlowRunPublic.trace_id" in rendered_signals
    assert "flow_dispatch_failed" in rendered_signals
    assert "flow_worker_stalled" in rendered_signals


def test_flow_developer_docs_reviewer_guide_source_references_exist() -> None:
    page = _read(FLOW_DEVELOPER_DOCS_REVIEWER_GUIDE)
    referenced_files = sorted(set(FLOW_DEVELOPER_SOURCE_FILE_REF_PATTERN.findall(page)))

    assert "backend/.importlinter" in referenced_files
    assert "backend/scripts/flow_developer_reviewer_guide_docs.py" in referenced_files
    assert (
        "frontend/apps/docs-site/src/content/docs/flows-for-developers/reviewing-flows-code.mdx"
        in referenced_files
    )
    assert referenced_files
    assert all(":" not in file_ref for file_ref in referenced_files)
    missing_files = [
        file_ref
        for file_ref in referenced_files
        if not (REPO_ROOT / file_ref).is_file()
    ]

    assert missing_files == []


def test_flow_developer_related_cards_match_section_navigation_titles() -> None:
    meta_titles = _flow_developer_meta_titles()
    pages_with_related = tuple(
        sorted(
            path
            for path in FLOW_DEVELOPER_DOCS_DIR.glob("*.mdx")
            if "## Related" in _read(path)
        )
    )

    assert pages_with_related == tuple(sorted(FLOW_DEVELOPER_DOCS_RELATED_CARD_PAGES))
    assert "## Related" not in _read(FLOW_DEVELOPER_DOCS_INDEX)

    for path in FLOW_DEVELOPER_DOCS_RELATED_CARD_PAGES:
        page = _read(path)
        related_section = _heading_section(page, "## Related")
        cards = _related_cards_from_page(page)

        assert "<Cards" in related_section
        assert "\n- [" not in related_section
        assert len(cards) == 2

        for title, href in cards:
            slug, target_path = _flow_developer_doc_for_href(href)
            assert target_path != path
            assert title == meta_titles[slug]


def test_flow_developer_reviewer_guide_validation_commands_name_checked_paths() -> None:
    generator = _load_flow_developer_reviewer_guide_docs_generator()
    generator.validate_reviewer_guide_catalog()

    for command in generator.REVIEWER_VALIDATION_COMMANDS:
        for referenced_path in command.referenced_paths:
            assert (REPO_ROOT / referenced_path).is_file()
            if not command.requires_path_arguments:
                continue
            command_path_token = referenced_path
            if command.workdir == "backend" and referenced_path.startswith("backend/"):
                command_path_token = referenced_path.removeprefix("backend/")
            if command.workdir == "frontend" and referenced_path.startswith(
                "frontend/"
            ):
                command_path_token = referenced_path.removeprefix("frontend/")
            assert command_path_token in command.command


def test_flow_developer_reviewer_guide_catalog_rejects_drift() -> None:
    generator = _load_flow_developer_reviewer_guide_docs_generator()
    topics = generator.REVIEWER_CHECKLIST_TOPICS
    routes = generator.REVIEWER_ROUTES
    commands = generator.REVIEWER_VALIDATION_COMMANDS
    first_topic = topics[0]
    first_route = routes[0]
    first_command = commands[0]
    first_checked_command_index = next(
        index
        for index, command in enumerate(commands)
        if command.requires_path_arguments
    )
    first_checked_command = commands[first_checked_command_index]

    with pytest.raises(ValueError, match="all review checklist topics"):
        generator.validate_reviewer_guide_catalog(topics=topics[:-1])

    with pytest.raises(ValueError, match="all review routes"):
        generator.validate_reviewer_guide_catalog(routes=routes[:-1])

    with pytest.raises(ValueError, match="all review validation commands"):
        generator.validate_reviewer_guide_catalog(commands=commands[:-1])

    missing_source = generator.ReviewerChecklistTopic(
        first_topic.slug,
        first_topic.title,
        first_topic.check,
        first_topic.reject,
        (
            generator.ReviewerGuideSourceRef(
                "Missing source",
                "backend/src/eneo/flows/does_not_exist.py",
            ),
        ),
    )
    with pytest.raises(ValueError, match="source ref file does not exist"):
        generator.validate_reviewer_guide_catalog(topics=(missing_source, *topics[1:]))

    over_budget = generator.ReviewerChecklistTopic(
        first_topic.slug,
        first_topic.title,
        "This check is intentionally long so the generated reviewer guide cannot turn into a large essay that repeats the implementation journal instead of giving reviewers a tight and directly useful rule that can be applied during code review.",
        first_topic.reject,
        first_topic.source_refs,
    )
    with pytest.raises(ValueError, match="one short sentence"):
        generator.validate_reviewer_guide_catalog(topics=(over_budget, *topics[1:]))

    table_pipe = generator.ReviewerChecklistTopic(
        first_topic.slug,
        first_topic.title,
        "Name the owner | then review the proof.",
        first_topic.reject,
        first_topic.source_refs,
    )
    with pytest.raises(ValueError, match="table pipes"):
        generator.validate_reviewer_guide_catalog(topics=(table_pipe, *topics[1:]))

    missing_route_source = generator.ReviewerRoute(
        first_route.slug,
        first_route.change_type,
        first_route.start_here,
        first_route.proof,
        (
            generator.ReviewerGuideSourceRef(
                "Missing route source",
                "backend/src/eneo/flows/no_route_owner.py",
            ),
        ),
    )
    with pytest.raises(ValueError, match="source ref file does not exist"):
        generator.validate_reviewer_guide_catalog(
            routes=(missing_route_source, *routes[1:])
        )

    procedure_without_steps = generator.ReviewerRoute(
        first_route.slug,
        first_route.change_type,
        first_route.start_here,
        first_route.proof,
        first_route.source_refs,
        "Broken procedure",
        (),
    )
    with pytest.raises(ValueError, match="title and steps together"):
        generator.validate_reviewer_guide_catalog(
            routes=(procedure_without_steps, *routes[1:])
        )

    too_short_procedure = generator.ReviewerRoute(
        first_route.slug,
        first_route.change_type,
        first_route.start_here,
        first_route.proof,
        first_route.source_refs,
        "Broken procedure",
        (generator.ProcedureStep("Open owner", "Open the owning source file."),),
    )
    with pytest.raises(ValueError, match="at least three steps"):
        generator.validate_reviewer_guide_catalog(
            routes=(too_short_procedure, *routes[1:])
        )

    path_in_step_title = generator.ReviewerRoute(
        first_route.slug,
        first_route.change_type,
        first_route.start_here,
        first_route.proof,
        first_route.source_refs,
        "Broken procedure",
        (
            generator.ProcedureStep("Open `runtime/executor.py`", "Open the owner."),
            generator.ProcedureStep("Change owner", "Change the owner."),
            generator.ProcedureStep("Test behavior", "Test behavior."),
        ),
    )
    with pytest.raises(ValueError, match="must not contain backticked paths"):
        generator.validate_reviewer_guide_catalog(
            routes=(path_in_step_title, *routes[1:])
        )

    duplicate_step_title_body = generator.ReviewerRoute(
        first_route.slug,
        first_route.change_type,
        first_route.start_here,
        first_route.proof,
        first_route.source_refs,
        "Broken procedure",
        (
            generator.ProcedureStep("Open owner", "Open owner"),
            generator.ProcedureStep("Change owner", "Change the owner."),
            generator.ProcedureStep("Test behavior", "Test behavior."),
        ),
    )
    with pytest.raises(ValueError, match="title must not duplicate body"):
        generator.validate_reviewer_guide_catalog(
            routes=(duplicate_step_title_body, *routes[1:])
        )

    empty_command_refs = generator.ReviewerValidationCommand(
        first_command.slug,
        first_command.label,
        first_command.command,
        first_command.workdir,
        first_command.when_to_run,
        (),
        first_command.requires_path_arguments,
    )
    with pytest.raises(ValueError, match="needs referenced paths"):
        generator.validate_reviewer_guide_catalog(
            commands=(empty_command_refs, *commands[1:])
        )

    missing_command_path = generator.ReviewerValidationCommand(
        first_command.slug,
        first_command.label,
        first_command.command,
        first_command.workdir,
        first_command.when_to_run,
        ("backend/tests/unittests/flows/no_docs_contract.py",),
        first_command.requires_path_arguments,
    )
    with pytest.raises(ValueError, match="command ref file does not exist"):
        generator.validate_reviewer_guide_catalog(
            commands=(missing_command_path, *commands[1:])
        )

    hidden_command_path = generator.ReviewerValidationCommand(
        first_checked_command.slug,
        first_checked_command.label,
        "set -a; source .env.template; set +a; uv run pytest tests/unittests/flows/test_flow_package_layout.py -q",
        first_checked_command.workdir,
        first_checked_command.when_to_run,
        first_checked_command.referenced_paths,
        first_checked_command.requires_path_arguments,
    )
    commands_with_hidden_path = list(commands)
    commands_with_hidden_path[first_checked_command_index] = hidden_command_path
    with pytest.raises(ValueError, match="must include checked path"):
        generator.validate_reviewer_guide_catalog(
            commands=tuple(commands_with_hidden_path)
        )

    node_id_command = generator.ReviewerValidationCommand(
        first_command.slug,
        first_command.label,
        f"{first_command.command}::test_flow_developer_docs_reviewer_guide_is_generated_from_review_catalog",
        first_command.workdir,
        first_command.when_to_run,
        first_command.referenced_paths,
        first_command.requires_path_arguments,
    )
    with pytest.raises(ValueError, match="must not use pytest node ids"):
        generator.validate_reviewer_guide_catalog(
            commands=(node_id_command, *commands[1:])
        )

    first_runbook_step = generator.REVIEWER_DEBUG_RUNBOOK_STEPS[0]
    duplicate_runbook_step = generator.ReviewerDebugRunbookStep(
        generator.REVIEWER_DEBUG_RUNBOOK_STEPS[1].slug,
        first_runbook_step.inspect,
        first_runbook_step.signals,
        first_runbook_step.next_action,
        first_runbook_step.source_refs,
    )
    with pytest.raises(ValueError, match="must not contain duplicates"):
        generator.validate_reviewer_guide_catalog(
            runbook_steps=(
                duplicate_runbook_step,
                *generator.REVIEWER_DEBUG_RUNBOOK_STEPS[1:],
            )
        )

    bad_signal_step = generator.ReviewerDebugRunbookStep(
        first_runbook_step.slug,
        first_runbook_step.inspect,
        ("flow.run.trace-id",),
        first_runbook_step.next_action,
        first_runbook_step.source_refs,
    )
    with pytest.raises(ValueError, match="unknown signal"):
        generator.validate_reviewer_guide_catalog(
            runbook_steps=(bad_signal_step, *generator.REVIEWER_DEBUG_RUNBOOK_STEPS[1:])
        )

    run_span_step_index = generator.REVIEWER_DEBUG_RUNBOOK_STEP_SLUGS.index(
        "run-span-correlation"
    )
    run_span_step = generator.REVIEWER_DEBUG_RUNBOOK_STEPS[run_span_step_index]
    missing_run_attribute_step = generator.ReviewerDebugRunbookStep(
        run_span_step.slug,
        run_span_step.inspect,
        tuple(
            signal
            for signal in run_span_step.signals
            if signal != "flow.celery.retry_count"
        ),
        run_span_step.next_action,
        run_span_step.source_refs,
    )
    runbook_steps_without_run_attribute = list(generator.REVIEWER_DEBUG_RUNBOOK_STEPS)
    runbook_steps_without_run_attribute[run_span_step_index] = (
        missing_run_attribute_step
    )
    with pytest.raises(ValueError, match="span attribute coverage"):
        generator.validate_reviewer_guide_catalog(
            runbook_steps=tuple(runbook_steps_without_run_attribute)
        )


def test_flow_schema_docs_exporter_rejects_missing_table_docstring() -> None:
    from eneo.flows.infrastructure.flow_schema_docs_exporter import (
        parse_flow_schema_model_docstring,
    )

    class MissingDocstring:
        __doc__ = None

    with pytest.raises(ValueError, match="must define a model docstring"):
        parse_flow_schema_model_docstring(
            MissingDocstring,
            table_name="missing_docstring",
        )


def test_flow_consumer_guides_are_generated_from_contract_catalogs() -> None:
    generators = _load_flow_consumer_guide_generators()
    pages = {
        "designing-flows": FLOW_CONSUMER_DESIGNING_GUIDE,
        "integrating-flows": FLOW_CONSUMER_INTEGRATING_GUIDE,
        "flows-faq": FLOW_CONSUMER_FAQ_GUIDE,
    }
    page_titles = {
        "designing-flows": "Designing Flows",
        "integrating-flows": "Integrating Flows",
        "flows-faq": "Flows FAQ",
    }
    guides_meta = _read(FLOW_GUIDES_META)
    section_meta = _read(FLOW_CONSUMER_SECTION_META)
    reference_meta = _read(FLOW_CONSUMER_REFERENCE_META)
    section_nav = _load_flow_consumer_section_docs_generator().FLOW_CONSUMER_SECTION_NAV

    assert '  flows: "Eneo Flows",' in guides_meta
    for legacy_slug in ("designing-flows", "integrating-flows", "flows-faq"):
        assert f'  "{legacy_slug}":' not in guides_meta
    assert [line for line in section_meta.splitlines() if line.startswith("  ")] == [
        f'  {_typescript_meta_key(entry.slug)}: "{entry.title}",'
        for entry in section_nav
    ]
    assert '  errors: "Error reference",' in reference_meta
    for legacy_path in FLOW_CONSUMER_LEGACY_FLAT_GUIDES:
        assert not legacy_path.exists()
    for slug, page_path in pages.items():
        generator = generators[slug]
        page = _read(page_path)

        generator.validate_flow_consumer_guide_catalog()
        assert generator.CONSUMER_GUIDE_PAGE_SLUG == slug
        _assert_generated_doc(
            page,
            generator.render_flow_consumer_guide_page(),
            path=page_path,
        )
        if "<Callout " in page:
            assert _non_empty_lines(page)[0] == (
                'import { Callout } from "nextra/components";'
            )
        else:
            assert 'from "nextra/components"' not in page
        _assert_purpose_header(page, page_titles[slug])
        assert _expected_next_line(slug, section_nav) in page
        assert page.count("Next: ") == 1
        assert "/guides/flows-api-guide" in page
        assert "Verified by:" not in page
        assert "test_" not in page
        assert PLACEHOLDER_DOC_PATTERN.search(page) is None


def test_flow_consumer_section_index_is_generated_from_nav_catalog() -> None:
    generator = _load_flow_consumer_section_docs_generator()
    page = _read(FLOW_CONSUMER_SECTION_INDEX)
    nav_entries = generator.FLOW_CONSUMER_SECTION_NAV

    generator.validate_flow_consumer_section_catalog()
    _assert_generated_doc(
        page,
        generator.render_flow_consumer_section_index_page(),
        path=FLOW_CONSUMER_SECTION_INDEX,
    )
    _assert_purpose_header(page, "Eneo Flows for API consumers")
    assert _expected_next_line("index", nav_entries) in page
    assert page.count("Next: ") == 1
    assert [entry.slug for entry in nav_entries] == [
        "index",
        "designing-flows",
        "integrating-flows",
        "flows-faq",
        "reference",
    ]
    for entry in nav_entries:
        if entry.slug == "index":
            continue
        assert entry.title in page
        assert entry.href in page
        assert entry.job in page
    assert "generated Flow error handling" not in page
    assert "/guides/flows-api-guide" in page
    assert "/guides/flows/reference/errors" in page
    assert PLACEHOLDER_DOC_PATTERN.search(page) is None


def test_flow_consumer_guides_keep_api_guide_as_reference_owner() -> None:
    guide = _read(FLOW_API_GUIDE)

    for slug in ("designing-flows", "integrating-flows", "flows-faq"):
        assert f"/guides/flows/{slug}" in guide

    for required_reference_term in (
        "FlowRunContractPublic",
        "FlowRuntimePathsPublic",
        "review_checkpoints",
        "step_inputs",
        "FlowApiErrorCode",
    ):
        assert required_reference_term in guide


def test_flow_consumer_deleted_flat_paths_are_not_linked_from_published_guides() -> (
    None
):
    offenders: list[str] = []

    for path in sorted(FLOW_GUIDES_DIR.rglob("*.mdx")):
        page = _read(path)
        for deleted_href in FLOW_CONSUMER_DELETED_FLAT_HREFS:
            if deleted_href in page:
                offenders.append(
                    f"{path.relative_to(REPO_ROOT)} still links {deleted_href}"
                )

    assert offenders == []


def test_flow_consumer_endpoint_receipts_and_fields_are_typed() -> None:
    runtime_path_fields = _flow_runtime_endpoint_field_names()
    run_contract_fields = _flow_run_contract_public_field_names()
    endpoint_operation_ids = {
        contract.operation_id for contract in FLOW_RUNTIME_ENDPOINT_CONTRACTS
    }
    sequences = [
        sequence
        for generator in _load_flow_consumer_guide_generators().values()
        for sequence in generator.ENDPOINT_SEQUENCES
    ]

    assert sequences

    for sequence in sequences:
        assert sequence.runtime_path_fields or sequence.run_contract_fields
        assert set(sequence.runtime_path_fields) <= runtime_path_fields
        assert set(sequence.run_contract_fields) <= run_contract_fields
        assert set(sequence.endpoint_operation_ids) <= endpoint_operation_ids
        assert sequence.receipts
        assert sequence.error_codes
        for code in sequence.error_codes:
            assert code in FlowApiErrorCode
        for receipt in sequence.receipts:
            test_file = REPO_ROOT / receipt.file_path
            assert test_file.is_file()
            assert f"def {receipt.function_name}" in _read(test_file)


def test_flow_consumer_docs_cover_every_runtime_endpoint_contract() -> None:
    generators = _load_flow_consumer_guide_generators()
    # The generator loader adds backend/scripts to sys.path for support imports.
    from flow_consumer_guide_support import documented_consumer_operation_ids

    documented_operation_ids: set[str] = set()
    for generator in generators.values():
        documented_operation_ids.update(
            documented_consumer_operation_ids(
                sequences=generator.ENDPOINT_SEQUENCES,
                worked_example_operation_ids=tuple(
                    hop.operation_id for hop in generator.WORKED_EXAMPLE_HOPS
                ),
                pitfall_rows=generator.ENDPOINT_PITFALL_ROWS,
            )
        )

    expected_operation_ids = {
        contract.operation_id for contract in FLOW_RUNTIME_ENDPOINT_CONTRACTS
    }

    assert documented_operation_ids - expected_operation_ids == set()
    assert expected_operation_ids - documented_operation_ids == set()


def test_flow_runtime_endpoint_registry_matches_constants_and_live_routes() -> None:
    registry_route_paths = {
        contract.route_path for contract in FLOW_RUNTIME_ENDPOINT_CONTRACTS
    }

    assert registry_route_paths == _flow_runtime_endpoint_route_paths()
    assert FLOW_ROOT_PATH not in registry_route_paths
    _assert_flow_runtime_endpoint_contracts_match_live_routes(
        FLOW_RUNTIME_ENDPOINT_CONTRACTS
    )


def test_flow_runtime_endpoint_registry_projects_every_runtime_path_field_once() -> (
    None
):
    _assert_flow_runtime_endpoint_fields_match_runtime_paths(
        FLOW_RUNTIME_ENDPOINT_CONTRACTS
    )


def test_flow_runtime_endpoint_registry_rejects_success_status_drift() -> None:
    broken_contracts = tuple(
        replace(contract, success_status=200)
        if contract.operation_id == "create_flow_run"
        else contract
        for contract in FLOW_RUNTIME_ENDPOINT_CONTRACTS
    )

    with pytest.raises(AssertionError):
        _assert_flow_runtime_endpoint_contracts_match_live_routes(broken_contracts)


def test_flow_runtime_endpoint_registry_rejects_missing_live_route_entry() -> None:
    broken_contracts = tuple(
        contract
        for contract in FLOW_RUNTIME_ENDPOINT_CONTRACTS
        if contract.operation_id != "list_flow_runs"
    )

    with pytest.raises(AssertionError):
        _assert_flow_runtime_endpoint_contracts_match_live_routes(broken_contracts)


def test_flow_runtime_endpoint_registry_rejects_missing_runtime_field_projection() -> (
    None
):
    broken_contracts = tuple(
        replace(
            contract,
            runtime_path_fields=(
                FlowRuntimePathFieldProjection(field_path=("graph",)),
            ),
        )
        if contract.operation_id == "get_flow_graph"
        else contract
        for contract in FLOW_RUNTIME_ENDPOINT_CONTRACTS
    )

    with pytest.raises(AssertionError):
        _assert_flow_runtime_endpoint_fields_match_runtime_paths(broken_contracts)


def test_flow_consumer_scenarios_map_to_buildable_goldens() -> None:
    from tests.unittests.flows.ai_builder.eval_matrix.golden_cases import (
        GOLDEN_CASES,
    )

    golden_ids = {case.case_id for case in GOLDEN_CASES}
    documented_scenarios = [
        scenario
        for generator in _load_flow_consumer_guide_generators().values()
        for scenario in generator.SCENARIOS
    ]

    assert "audio_to_docx_template__advanced" in golden_ids
    assert documented_scenarios

    for scenario in documented_scenarios:
        assert scenario.golden_ids
        assert set(scenario.golden_ids) <= golden_ids


def test_flow_consumer_capability_matrix_is_manifest_backed_and_bounded() -> None:
    designing_generator = _load_flow_consumer_guide_docs_generator(
        "flow_consumer_designing_flows_docs",
        FLOW_CONSUMER_DESIGNING_GUIDE_DOCS_GENERATOR,
    )
    page = _read(FLOW_CONSUMER_DESIGNING_GUIDE)
    artifacts = set(FINAL_OUTPUT_ARTIFACT_BY_TYPE.values())
    rows = designing_generator.CAPABILITY_MATRIX_ROWS

    assert 1 <= len(rows) <= designing_generator.CAPABILITY_MATRIX_ROW_BUDGET <= 15
    assert {row.output_artifact for row in rows} == artifacts
    assert "Image input is not supported" in page
    assert "Closest supported alternative" in page
    for row in rows:
        assert row.output_artifact in artifacts
        assert row.input_mode
        assert row.output_types
        assert row.output_modes


def test_flow_consumer_endpoint_pitfall_matrix_is_source_backed() -> None:
    from flow_consumer_guide_support import success_status_label

    faq_generator = _load_flow_consumer_guide_docs_generator(
        "flow_consumer_faq_docs",
        FLOW_CONSUMER_FAQ_GUIDE_DOCS_GENERATOR,
    )
    page = _read(FLOW_CONSUMER_FAQ_GUIDE)
    errors_page = _read(FLOW_CONSUMER_ERROR_REFERENCE)
    failures_page = _read(FLOW_DEVELOPER_DOCS_WHEN_THINGS_FAIL)
    rows = faq_generator.ENDPOINT_PITFALL_ROWS
    required_categories = {
        "idempotency",
        "polling",
        "async_accepted",
        "artifact_retention",
        "outbound_delivery_failure",
    }
    contracts_by_operation = flow_runtime_endpoint_by_operation_id()

    assert "## Capability and endpoint pitfalls" in page
    assert "`GET export_flow_run_evidence`" in page
    assert {row.category for row in rows} == required_categories
    assert rows

    async_operation_ids = tuple(
        contract.operation_id
        for contract in FLOW_RUNTIME_ENDPOINT_CONTRACTS
        if contract.success_status == 202
    )
    async_row = next(row for row in rows if row.category == "async_accepted")
    assert async_row.operation_ids == async_operation_ids

    for row in rows:
        assert row.capability in page
        assert row.operation_ids
        for operation_id in row.operation_ids:
            contract = contracts_by_operation[operation_id]
            assert f"`{contract.method.upper()} {contract.operation_id}`" in page
            assert f"`{success_status_label(contract.success_status)}`" in page
        if row.error_code is not None:
            expected_action = FLOW_ERROR_TAXONOMY[row.error_code].consumer_action
        else:
            expected_action = row.consumer_action
        assert expected_action
        assert expected_action in page

    delivery_action = FLOW_ERROR_TAXONOMY[
        FlowApiErrorCode.WEBHOOK_DELIVERY_FAILED
    ].consumer_action
    assert "retry delivery if the API supports it" not in delivery_action
    assert "automatic delivery retries" not in delivery_action
    assert "delivery retries are exhausted" in delivery_action
    assert "no public redelivery endpoint exists" in delivery_action
    assert delivery_action in errors_page
    assert delivery_action in failures_page

    assert "Idempotency: reuse a key only" not in page
    assert "Polling: poll run and step endpoints" not in page
    assert "Retention: follow tenant retention settings" not in page


def test_flow_consumer_guides_document_unsupported_features_with_alternatives() -> None:
    callouts = [
        callout
        for generator in _load_flow_consumer_guide_generators().values()
        for callout in generator.UNSUPPORTED_CALLOUTS
    ]
    pages = (
        _read(FLOW_CONSUMER_DESIGNING_GUIDE)
        + _read(FLOW_CONSUMER_INTEGRATING_GUIDE)
        + _read(FLOW_CONSUMER_FAQ_GUIDE)
    )

    assert callouts
    assert any(callout.feature == "Image input" for callout in callouts)
    assert any(callout.feature == "Arbitrary mid-run pause" for callout in callouts)
    assert any(
        callout.feature == "AI Builder-authored HTTP steps" for callout in callouts
    )
    assert any(callout.feature == "Run-status webhooks" for callout in callouts)
    assert INPUT_TYPE_POLICIES["image"].supported is False
    assert CAPABILITY_REGISTRY["input_image"].exposure == "not_exposed"
    assert CAPABILITY_REGISTRY["input_image"].not_exposed_reason

    for callout in callouts:
        assert callout.feature in pages
        assert callout.supported_alternative in pages

    assert "webhook delivery" not in pages


def test_flow_consumer_callouts_render_typed_nextra_warning() -> None:
    generators = _load_flow_consumer_guide_generators()
    page_by_slug = {
        "designing-flows": _read(FLOW_CONSUMER_DESIGNING_GUIDE),
        "integrating-flows": _read(FLOW_CONSUMER_INTEGRATING_GUIDE),
        "flows-faq": _read(FLOW_CONSUMER_FAQ_GUIDE),
    }

    for slug, generator in generators.items():
        page = page_by_slug[slug]
        if generator.UNSUPPORTED_CALLOUTS:
            assert page.startswith('import { Callout } from "nextra/components";\n')
        for callout in generator.UNSUPPORTED_CALLOUTS:
            assert callout.type == "warning"
            assert '<Callout type="warning">' in page
            assert f"**Not supported: {callout.feature}.**" in page
            assert callout.supported_alternative in page

    designing = page_by_slug["designing-flows"]
    all_pages = "\n".join(page_by_slug.values())
    assert "**Anti-pattern: One giant step.**" in designing
    assert "Better design: split extraction" in designing
    assert "> **Not supported:" not in all_pages
    assert "> **Anti-pattern:" not in designing


def test_flow_consumer_callouts_reject_unescaped_jsx_text() -> None:
    _load_flow_consumer_guide_generators()
    from flow_consumer_guide_support import (
        UnsupportedCallout,
        validate_unsupported_callouts,
    )

    unsafe_feature = UnsupportedCallout(
        feature="Bad {feature}",
        reason="This would become JSX text.",
        supported_alternative="Keep braces inside backticks.",
    )
    unsafe_alternative = UnsupportedCallout(
        feature="Unsafe tag",
        reason="This would become JSX text.",
        supported_alternative="Use <a supported value> only when escaped.",
    )
    empty_alternative = UnsupportedCallout(
        feature="Empty alternative",
        reason="This would become ambiguous guidance.",
        supported_alternative="",
    )

    with pytest.raises(ValueError, match="JSX-safe"):
        validate_unsupported_callouts((unsafe_feature,))
    with pytest.raises(ValueError, match="JSX-safe"):
        validate_unsupported_callouts((unsafe_alternative,))
    with pytest.raises(ValueError, match="must not be empty"):
        validate_unsupported_callouts((empty_alternative,))


def test_flow_consumer_page_prose_fields_are_guarded() -> None:
    _load_flow_consumer_guide_generators()
    from flow_consumer_guide_support import GuidePage, render_page

    with pytest.raises(ValueError, match="old generated header"):
        render_page(
            GuidePage(
                slug="designing-flows",
                title="Designing Flows",
                purpose="**Read this when ...** you are deciding what to build.",
                orientation="You are in the design step.",
                body=("Body.",),
            )
        )
    with pytest.raises(ValueError, match="one short sentence"):
        render_page(
            GuidePage(
                slug="designing-flows",
                title="Designing Flows",
                purpose="First sentence.\nSecond sentence.",
                orientation="You are in the design step.",
                body=("Body.",),
            )
        )
    with pytest.raises(ValueError, match="consumer section nav"):
        render_page(
            GuidePage(
                slug="unknown-page",
                title="Unknown",
                purpose="This page has no place in the consumer journey.",
                orientation="The renderer should reject this slug.",
                body=("Body.",),
            )
        )


def test_flow_consumer_guides_answer_fresh_reader_edge_cases() -> None:
    designing = _read(FLOW_CONSUMER_DESIGNING_GUIDE)
    integrating = _read(FLOW_CONSUMER_INTEGRATING_GUIDE)

    assert "DOCX artifact (`template_fill`)" in designing
    assert "file id from run or step `result_files`" in integrating
    assert "not direct post-run output edits" in integrating


def test_flow_consumer_guide_json_examples_are_valid_json() -> None:
    invalid_blocks: list[str] = []

    for path in (
        FLOW_CONSUMER_DESIGNING_GUIDE,
        FLOW_CONSUMER_INTEGRATING_GUIDE,
        FLOW_CONSUMER_FAQ_GUIDE,
    ):
        blocks = JSON_CODE_BLOCK_PATTERN.findall(_read(path))
        for index, block in enumerate(blocks, start=1):
            try:
                json.loads(block)
            except json.JSONDecodeError as exc:
                invalid_blocks.append(f"{path.name} json block {index}: {exc}")

    assert invalid_blocks == []


def test_flow_api_guide_json_examples_are_valid_json() -> None:
    guide = _read(FLOW_API_GUIDE)
    invalid_blocks: list[str] = []

    for index, block in enumerate(JSON_CODE_BLOCK_PATTERN.findall(guide), start=1):
        try:
            json.loads(block)
        except json.JSONDecodeError as exc:
            invalid_blocks.append(f"json block {index}: {exc}")

    assert invalid_blocks == []


def test_flow_api_guide_pins_canonical_runtime_response_examples() -> None:
    runtime_example = build_flow_runtime_public_example()
    run_contract_example = FLOW_RUN_CONTRACT_PUBLIC_EXAMPLE

    FlowRuntimePathsPublic.model_validate(runtime_example["runtime_paths"])
    FlowRunContractPublic.model_validate(run_contract_example)

    assert (
        _find_json_object(
            FLOW_API_GUIDE,
            required_keys={"id", "space_id", "published_version", "runtime_paths"},
        )
        == runtime_example
    )
    assert (
        _find_json_object(
            FLOW_API_GUIDE,
            required_keys={
                "flow_id",
                "published_flow_version",
                "final_output",
                "steps_requiring_input",
                "template_readiness",
            },
        )
        == run_contract_example
    )


def test_flow_api_guide_pins_canonical_run_and_step_examples() -> None:
    FlowRunCreateRequest.model_validate(_flow_run_create_request_example())
    FlowRunPublic.model_validate(FLOW_RUN_PUBLIC_EXAMPLE)
    FlowRunStepPublic.model_validate(FLOW_RUN_STEP_PUBLIC_EXAMPLE)

    assert (
        _find_json_object(
            FLOW_API_GUIDE,
            required_keys={
                "expected_flow_version",
                "input_payload_json",
                "step_inputs",
            },
        )
        == _flow_run_create_request_example()
    )
    assert (
        _find_json_object(
            FLOW_API_GUIDE,
            required_keys={"flow_version", "tenant_id", "trace_id", "status", "error"},
        )
        == FLOW_RUN_PUBLIC_EXAMPLE
    )
    assert _find_json_list(
        FLOW_API_GUIDE,
        required_keys={"flow_run_id", "step_id", "status", "error_code"},
    ) == [FLOW_RUN_STEP_PUBLIC_EXAMPLE]


def test_flow_api_guide_pins_canonical_file_and_signed_url_examples() -> None:
    FilePublic.model_validate(FILE_PUBLIC_EXAMPLE)
    SignedURLRequest.model_validate(_signed_url_request_example())
    SignedURLResponse.model_validate(SIGNED_URL_RESPONSE_EXAMPLE)

    assert (
        _find_json_object(
            FLOW_API_GUIDE,
            required_keys={"id", "name", "mimetype", "size"},
        )
        == FILE_PUBLIC_EXAMPLE
    )
    assert (
        _find_json_object(
            FLOW_API_GUIDE,
            required_keys={"expires_in", "content_disposition"},
        )
        == _signed_url_request_example()
    )
    assert (
        _find_json_object(
            FLOW_API_GUIDE,
            required_keys={"url", "expires_at"},
        )
        == SIGNED_URL_RESPONSE_EXAMPLE
    )

    guide = _read(FLOW_API_GUIDE)
    assert "`expires_in` defaults to `3600` seconds" in guide
    assert "does not enforce a minimum or maximum" in guide


def test_flow_api_guide_pins_canonical_review_checkpoint_examples() -> None:
    FlowRunReviewCheckpointPublic.model_validate(
        FLOW_RUN_REVIEW_CHECKPOINT_PUBLIC_EXAMPLE
    )
    FlowRunReviewCheckpointEditRequest.model_validate(
        FLOW_RUN_REVIEW_CHECKPOINT_EDIT_REQUEST_EXAMPLE
    )

    assert (
        _find_json_object(
            FLOW_API_GUIDE,
            required_keys={
                "flow_run_id",
                "state",
                "original_payload_json",
                "current_payload_json",
                "review_mode",
            },
        )
        == FLOW_RUN_REVIEW_CHECKPOINT_PUBLIC_EXAMPLE
    )
    assert (
        _find_json_object(
            FLOW_API_GUIDE,
            required_keys={"expected_checkpoint_revision", "current_payload_json"},
        )
        == FLOW_RUN_REVIEW_CHECKPOINT_EDIT_REQUEST_EXAMPLE
    )


def test_flow_consumer_guides_pin_create_and_review_edit_examples() -> None:
    generator = _load_flow_consumer_guide_docs_generator(
        "flow_consumer_integrating_flows_docs",
        FLOW_CONSUMER_INTEGRATING_GUIDE_DOCS_GENERATOR,
    )
    integrating = _read(FLOW_CONSUMER_INTEGRATING_GUIDE)

    FlowRunReviewCheckpointEditRequest.model_validate(
        generator.WORKED_EXAMPLE_CHECKPOINT_EDIT_REQUEST
    )
    assert (
        _find_json_object(
            FLOW_CONSUMER_INTEGRATING_GUIDE,
            required_keys={
                "expected_flow_version",
                "input_payload_json",
                "step_inputs",
            },
        )
        == _flow_run_create_request_example()
    )
    assert (
        _find_json_object(
            FLOW_CONSUMER_INTEGRATING_GUIDE,
            required_keys={"expected_checkpoint_revision", "current_payload_json"},
        )
        == generator.WORKED_EXAMPLE_CHECKPOINT_EDIT_REQUEST
    )
    assert (
        "transcription"
        in generator.WORKED_EXAMPLE_CHECKPOINT_EDIT_REQUEST["current_payload_json"]
    )
    assert "edited_output" not in integrating
    assert "run-level `error_code`" not in integrating
    assert "run-level `error.code`" in integrating


def test_flow_consumer_integrating_guide_renders_source_backed_worked_example() -> None:
    generator = _load_flow_consumer_guide_docs_generator(
        "flow_consumer_integrating_flows_docs",
        FLOW_CONSUMER_INTEGRATING_GUIDE_DOCS_GENERATOR,
    )
    from flow_consumer_guide_support import (
        endpoint_contracts_for_sequence,
        success_status_label,
    )

    page = _read(FLOW_CONSUMER_INTEGRATING_GUIDE)
    endpoint_by_operation_id = flow_runtime_endpoint_by_operation_id()

    assert "## Sequence overview" in page
    assert page.index("## Sequence overview") < page.index(
        "## Worked end-to-end example"
    )
    sequence_overview = page.split("## Sequence overview", maxsplit=1)[1].split(
        "## Worked end-to-end example",
        maxsplit=1,
    )[0]
    assert "Key endpoint" in sequence_overview
    assert "Entry endpoint" not in sequence_overview
    assert "Endpoint facts:" not in sequence_overview
    assert "Success" not in sequence_overview
    for sequence in generator.ENDPOINT_SEQUENCES:
        entry_contract = endpoint_contracts_for_sequence(sequence)[0]
        entry_endpoint = build_flow_endpoint_template(
            entry_contract.route_path,
            api_prefix="/api/v1",
        )
        assert sequence.title in sequence_overview
        assert sequence.summary in sequence_overview
        assert f"`{entry_contract.method.upper()} {entry_endpoint}`" in (
            sequence_overview
        )
        assert f"`{entry_contract.operation_id}`" in sequence_overview
    assert page.count("Endpoint facts:") == len(generator.ENDPOINT_SEQUENCES)

    assert "## Worked end-to-end example" in page
    assert "## Request shapes" not in page
    assert "multipart/form-data" in page
    assert "Each response below is a public example for that hop." in page
    assert "Idempotency-Key: audio-report-alex-example-2026-03-17" in page
    assert "Idempotency-Key: review-resume-" in page
    assert FlowApiErrorCode.REVIEW_IDEMPOTENCY_KEY_REQUIRED.value in page
    assert "no single-step GET" in page
    assert "filter the list by `step_id`" in page
    assert generator.FLOW_RUN_AWAITING_REVIEW_RESPONSE_EXAMPLE == {
        **FLOW_RUN_QUEUED_AFTER_DISPATCH_EXAMPLE,
        "revision": 2,
        "status": "awaiting_review",
        "dispatch_next_attempt_at": None,
        "started_at": "2026-03-17T10:05:02Z",
        "updated_at": "2026-03-17T10:05:30Z",
    }
    for stale_text in ("Review draft answer", "Draft answer.", "Edited answer."):
        assert stale_text not in page

    expected_operations = (
        "get_flow_run_contract",
        "upload_flow_runtime_file",
        "create_flow_run",
        "get_flow_run",
        "get_active_flow_run_review_checkpoint",
        "edit_flow_run_review_checkpoint",
        "approve_flow_run_review_checkpoint",
        "resume_flow_run_review_checkpoint",
        "list_flow_run_steps",
        "generate_flow_run_artifact_signed_url",
    )
    assert tuple(hop.operation_id for hop in generator.WORKED_EXAMPLE_HOPS) == (
        expected_operations
    )
    expected_success_statuses = {
        "get_flow_run_contract": 200,
        "upload_flow_runtime_file": 201,
        "create_flow_run": 201,
        "get_flow_run": 200,
        "get_active_flow_run_review_checkpoint": 200,
        "edit_flow_run_review_checkpoint": 200,
        "approve_flow_run_review_checkpoint": 200,
        "resume_flow_run_review_checkpoint": 202,
        "list_flow_run_steps": 200,
        "generate_flow_run_artifact_signed_url": 200,
    }
    for hop in generator.WORKED_EXAMPLE_HOPS:
        contract = endpoint_by_operation_id[hop.operation_id]
        assert contract.success_status == expected_success_statuses[hop.operation_id]
        endpoint = build_flow_endpoint_template(
            contract.route_path,
            api_prefix="/api/v1",
        )
        assert hop.title in page
        assert f"`{endpoint}`" in page
        assert f"`{contract.method.upper()}`" in page
        assert f"`{success_status_label(contract.success_status)}`" in page
        assert f"`{contract.operation_id}`" in page

    assert (
        _find_json_object(
            FLOW_CONSUMER_INTEGRATING_GUIDE,
            required_keys={"flow_id", "published_flow_version", "final_output"},
        )
        == FLOW_RUN_CONTRACT_PUBLIC_EXAMPLE
    )
    _assert_json_object_present(FLOW_CONSUMER_INTEGRATING_GUIDE, FILE_PUBLIC_EXAMPLE)
    _assert_json_object_present(
        FLOW_CONSUMER_INTEGRATING_GUIDE, FLOW_RUN_PUBLIC_EXAMPLE
    )
    FlowRunReviewCheckpointPublic.model_validate(generator.WORKED_EXAMPLE_CHECKPOINT)
    FlowRunReviewCheckpointPublic.model_validate(
        generator.WORKED_EXAMPLE_CHECKPOINT_EDITED_RESPONSE
    )
    FlowRunReviewCheckpointPublic.model_validate(
        generator.WORKED_EXAMPLE_CHECKPOINT_APPROVED_RESPONSE
    )
    FlowRunReviewCheckpointResumeResponse.model_validate(
        generator.WORKED_EXAMPLE_CHECKPOINT_RESUME_RESPONSE
    )
    FlowRunStepPublic.model_validate(generator.WORKED_EXAMPLE_FINAL_STEP_RESULT)
    FlowRunStepResultFile.model_validate(generator.WORKED_EXAMPLE_ARTIFACT_RESULT_FILE)
    SignedURLResponse.model_validate(generator.WORKED_EXAMPLE_SIGNED_URL_RESPONSE)

    review_step = cast(
        dict[str, object],
        FLOW_RUN_CONTRACT_PUBLIC_EXAMPLE["steps_requiring_review"][0],
    )
    input_step = cast(
        dict[str, object],
        FLOW_RUN_CONTRACT_PUBLIC_EXAMPLE["steps_requiring_input"][0],
    )
    final_output = cast(
        dict[str, object],
        FLOW_RUN_CONTRACT_PUBLIC_EXAMPLE["final_output"],
    )
    create_request = _flow_run_create_request_example()
    step_inputs = cast(dict[str, object], create_request["step_inputs"])
    input_file_binding = cast(
        dict[str, object], step_inputs[str(input_step["step_id"])]
    )
    assert input_file_binding["file_ids"] == [FILE_PUBLIC_EXAMPLE["id"]]

    checkpoint = generator.WORKED_EXAMPLE_CHECKPOINT
    assert checkpoint["step_id"] == review_step["step_id"]
    assert checkpoint["step_order"] == review_step["step_order"]
    assert checkpoint["step_label"] == review_step["label"]
    assert checkpoint["output_contract"] == review_step["output_contract"]
    assert checkpoint["next_step_ids"] == [final_output["step_id"]]
    assert "transcription" in cast(
        dict[str, object], checkpoint["current_payload_json"]
    )
    assert "text" not in cast(dict[str, object], checkpoint["current_payload_json"])

    edited = generator.WORKED_EXAMPLE_CHECKPOINT_EDITED_RESPONSE
    approved = generator.WORKED_EXAMPLE_CHECKPOINT_APPROVED_RESPONSE
    edit_request = generator.WORKED_EXAMPLE_CHECKPOINT_EDIT_REQUEST
    approve_request = FLOW_RUN_REVIEW_CHECKPOINT_APPROVE_REQUEST_EXAMPLE
    resume_request = FLOW_RUN_REVIEW_CHECKPOINT_RESUME_REQUEST_EXAMPLE
    resumed_checkpoint = cast(
        dict[str, object],
        generator.WORKED_EXAMPLE_CHECKPOINT_RESUME_RESPONSE["checkpoint"],
    )
    assert edited["id"] == checkpoint["id"]
    assert approved["id"] == checkpoint["id"]
    assert resumed_checkpoint["id"] == checkpoint["id"]
    assert edit_request["expected_checkpoint_revision"] == checkpoint["revision"]
    assert approve_request["expected_checkpoint_revision"] == edited["revision"]
    assert resume_request["expected_checkpoint_revision"] == approved["revision"]
    assert edited["edited_at"] is not None
    assert edited["decided_by_principal_type"] is not None
    assert approved["approved_at"] is not None
    assert resumed_checkpoint["resumed_at"] is not None
    for checkpoint_document in (checkpoint, edited, approved, resumed_checkpoint):
        payload = cast(dict[str, object], checkpoint_document["current_payload_json"])
        assert "transcription" in payload
        assert "text" not in payload

    _assert_json_object_present(
        FLOW_CONSUMER_INTEGRATING_GUIDE,
        generator.WORKED_EXAMPLE_CHECKPOINT,
    )
    assert _find_json_list(
        FLOW_CONSUMER_INTEGRATING_GUIDE,
        required_keys={"flow_run_id", "step_id", "status", "error_code"},
    ) == [generator.WORKED_EXAMPLE_FINAL_STEP_RESULT]
    final_step_result = generator.WORKED_EXAMPLE_FINAL_STEP_RESULT
    artifact_file = generator.WORKED_EXAMPLE_ARTIFACT_RESULT_FILE
    assert final_step_result["step_id"] == final_output["step_id"]
    assert final_step_result["step_order"] == final_output["step_order"]
    final_step_input_payload = cast(
        dict[str, object],
        final_step_result["input_payload_json"],
    )
    assert final_step_input_payload["source_step_ids"] == [review_step["step_id"]]
    assert final_step_result["runtime_input_file_ids"] == []
    assert final_step_result["output_payload_json"] is None
    assert final_step_result["diagnostics"] == []
    assert artifact_file["step_id"] == final_output["step_id"]
    assert artifact_file["step_order"] == final_output["step_order"]
    assert artifact_file["step_result_id"] == final_step_result["id"]
    assert artifact_file["file_type"] == "document"
    assert artifact_file["source"] == "generated_output"
    assert artifact_file["name"] == "annual-review-report.docx"
    assert (
        artifact_file["mimetype"]
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert final_step_result["result_files"] == [artifact_file]
    assert (
        _find_json_object(
            FLOW_CONSUMER_INTEGRATING_GUIDE,
            required_keys={"expires_in", "content_disposition"},
        )
        == _signed_url_request_example()
    )
    artifact_file_id = str(artifact_file["file_id"])
    assert artifact_file_id != FILE_PUBLIC_EXAMPLE["id"]
    assert artifact_file_id in page
    assert (
        _find_json_object(
            FLOW_CONSUMER_INTEGRATING_GUIDE,
            required_keys={"url", "expires_at"},
        )
        == generator.WORKED_EXAMPLE_SIGNED_URL_RESPONSE
    )
    signed_url = cast(str, generator.WORKED_EXAMPLE_SIGNED_URL_RESPONSE["url"])
    assert artifact_file_id in signed_url
    assert FILE_PUBLIC_EXAMPLE["id"] not in signed_url


def test_flow_api_guide_documents_full_step_status_enumeration() -> None:
    guide = _read(FLOW_API_GUIDE)

    missing_statuses = sorted(
        status.value for status in FlowStepResultStatus if status.value not in guide
    )

    assert missing_statuses == []


def test_flow_api_guide_documents_run_contract_public_fields() -> None:
    guide = _read(FLOW_API_GUIDE)
    required_fields = set(FlowRunContractPublic.model_fields)

    missing_fields = sorted(field for field in required_fields if field not in guide)

    assert missing_fields == []


def test_flow_api_guide_documents_runtime_path_fields() -> None:
    guide = _read(FLOW_API_GUIDE)
    required_fields = set(FlowRuntimePathsPublic.model_fields) | {
        f"review_checkpoints.{field}"
        for field in FlowReviewCheckpointRuntimePathsPublic.model_fields
    }

    missing_fields = sorted(
        field
        for field in required_fields
        if field not in guide and field.split(".")[-1] not in guide
    )

    assert missing_fields == []


def test_flow_api_guide_documents_run_statuses_and_capabilities_endpoint() -> None:
    guide = _read(FLOW_API_GUIDE)

    missing_statuses = sorted(
        status.value for status in FlowRunStatus if status.value not in guide
    )

    assert missing_statuses == []
    assert "/api/v1/flows/runs/status-capabilities/" in guide
    for capability in (
        "should_poll",
        "is_terminal",
        "is_cancellable",
        "is_awaiting_review",
        "can_request_redispatch",
    ):
        assert capability in guide


def test_flow_consumer_error_reference_is_generated_from_taxonomy() -> None:
    generator = _load_flow_consumer_error_catalog_docs_generator()
    page = _read(FLOW_CONSUMER_ERROR_REFERENCE)
    guide = _read(FLOW_API_GUIDE)

    rows = generator.flow_consumer_error_catalog_rows()
    documented_codes = _flow_error_code_table_values(FLOW_CONSUMER_ERROR_REFERENCE)

    _assert_generated_doc(
        page,
        generator.render_flow_consumer_error_reference_page(),
        path=FLOW_CONSUMER_ERROR_REFERENCE,
    )
    _assert_purpose_header(page, "Flow error reference")
    assert "/guides/flows-api-guide" in page
    assert {row.code for row in rows} == {code.value for code in FlowApiErrorCode}
    assert documented_codes == {code.value for code in FlowApiErrorCode}
    assert page.count("`flow_") + page.count("`typed_io_") == len(FlowApiErrorCode)
    assert "Handling phase" in page
    assert "| Surface |" not in page
    assert "### Runtime error codes" not in guide
    assert "flow-error-catalog" not in guide
    assert "/guides/flows/reference/errors" in guide
    assert "generated catalog above" not in guide
    assert (
        "For Flow-specific codes, use [Flow error reference](/guides/flows/reference/errors)"
        in guide
    )


def test_flow_owned_mdx_docs_use_mdx_comment_syntax() -> None:
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in FLOW_OWNED_MDX_DOCS
        if "<!--" in _read(path)
    ]

    assert offenders == [], (
        "Flow docs use MDX comments: `{/* ... */}`. Raw HTML comments broke "
        f"the docs-site build in: {offenders}"
    )


def test_flow_owned_mdx_diagram_assets_exist() -> None:
    missing_assets: list[str] = []

    for path in FLOW_OWNED_MDX_DOCS:
        for diagram_path in DOCS_SITE_DIAGRAM_PATH_PATTERN.findall(_read(path)):
            asset_path = DOCS_SITE_PUBLIC_DIR / diagram_path.removeprefix("/")
            if not asset_path.is_file():
                missing_assets.append(
                    f"{path.relative_to(REPO_ROOT)} -> {diagram_path}"
                )

    assert missing_assets == [], (
        f"Flow docs reference missing docs-site diagram assets: {missing_assets}"
    )


def test_generated_flow_docs_use_natural_purpose_headers() -> None:
    offenders: list[str] = []

    for path in GENERATED_FLOW_DOCS_WITH_STANDARD_HEADER:
        page = _read(path)
        if "Read this when" in page or "After reading you can" in page:
            offenders.append(str(path.relative_to(REPO_ROOT)))

    assert offenders == []
    developer_index = _read(FLOW_DEVELOPER_DOCS_INDEX)
    assert "Read this when" not in developer_index
    assert "After reading you can" not in developer_index


def test_flow_api_guide_reserved_input_payload_keys_match_backend_source() -> None:
    guide = _read(FLOW_API_GUIDE)
    match = RESERVED_INPUT_PAYLOAD_KEYS_PATTERN.search(guide)

    assert match is not None
    documented_keys = set(BACKTICKED_TOKEN_PATTERN.findall(match.group("keys")))

    assert documented_keys == FLOW_RUN_RESERVED_INPUT_PAYLOAD_KEYS


def test_flow_api_guide_does_not_teach_stale_run_response_shape() -> None:
    guide = _read(FLOW_API_GUIDE)
    run_response = _find_json_object(
        FLOW_API_GUIDE,
        required_keys={"flow_version", "tenant_id", "trace_id", "status", "error"},
    )

    assert "user_id" not in run_response
    assert "error_message" not in run_response
    assert "flow as a whole, not one step at a time" not in guide


def test_flow_overview_matches_implemented_runtime_retention_scope() -> None:
    overview = _read(FLOW_OVERVIEW)
    guide = _read(FLOW_API_GUIDE)

    assert "run_debug_evidence_days" in overview
    assert "layered retention policy" not in overview
    assert "full run-history purge window" in overview
    assert "1..2555" in overview
    assert "1..2555" in guide
    assert "/api/v1/settings/flow-classification-retention-policies" in overview
    assert "/api/v1/settings/flow-classification-retention-policies" in guide
    assert "security_enabled" in overview
    assert "Classification policies tighten" in guide
    assert "earlier debug-evidence redaction window" in overview
    assert "unreferenced generated result files" in overview
    assert "Reusable runtime uploads" in overview
    assert "Purge is deferred while a run still has undelivered audit events" in (
        overview
    )
    assert "Purge is deferred while a run still has undelivered audit events" in guide
    assert "There is no API for raw per-step deletion intervals yet." in guide
