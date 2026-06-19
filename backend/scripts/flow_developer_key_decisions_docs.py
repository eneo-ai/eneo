from __future__ import annotations

import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = REPO_ROOT / "backend" / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

from intric.flows.infrastructure.flow_docs_mermaid import (  # noqa: E402
    render_flow_docs_mermaid_block,
)
from intric.flows.infrastructure.flow_docs_related_cards import (  # noqa: E402
    FLOW_DOCS_RELATED_NEXTRA_CARDS_IMPORT,
    FlowDocsRelatedNextraCard,
    render_flow_docs_related_nextra_cards,
)

FLOW_DEVELOPER_KEY_DECISIONS_DOCS_OUTPUT_PATH = (
    REPO_ROOT
    / "frontend"
    / "apps"
    / "docs-site"
    / "src"
    / "content"
    / "docs"
    / "flows-for-developers"
    / "key-decisions.mdx"
)

FLOW_DEVELOPER_KEY_DECISION_SLUGS = (
    "relational-step-input-files",
    "typed-lifecycle-exceptions",
    "explicit-flow-principals",
    "authored-http-config-only",
    "review-checkpoint-persistence-owner",
    "bounded-jsonb-policy",
    "public-flow-api-error-codes",
    "import-boundaries",
    "review-checkpoint-state-machine",
    "rerun-lineage",
)

_MAX_FIELD_LENGTH = 230
_SENTENCE_END_PATTERN = re.compile(r"[.!?]")


@dataclass(frozen=True, slots=True)
class FlowDecisionSourceRef:
    label: str
    path: str


@dataclass(frozen=True, slots=True)
class FlowDeveloperKeyDecision:
    slug: str
    title: str
    context: str
    decision: str
    consequences: tuple[str, ...]
    source_refs: tuple[FlowDecisionSourceRef, ...]


def _source(label: str, path: str) -> FlowDecisionSourceRef:
    return FlowDecisionSourceRef(label=label, path=path)


def _decision(
    slug: str,
    title: str,
    context: str,
    decision: str,
    consequences: tuple[str, ...],
    source_refs: tuple[FlowDecisionSourceRef, ...],
) -> FlowDeveloperKeyDecision:
    return FlowDeveloperKeyDecision(
        slug=slug,
        title=title,
        context=context,
        decision=decision,
        consequences=consequences,
        source_refs=source_refs,
    )


FLOW_DEVELOPER_KEY_DECISIONS: tuple[FlowDeveloperKeyDecision, ...] = (
    _decision(
        slug="relational-step-input-files",
        title="Relational step-input files over rerun JSON blobs",
        context="Runtime files need auditability, tenant scoping, and file foreign keys.",
        decision="`FlowRunStepInputFiles` is the canonical owner for step-file bindings.",
        consequences=(
            "Reject new step-input JSON side channels that duplicate relational file rows.",
            "Keep rerun override intent explicit with `root_step_input_override_requested`.",
        ),
        source_refs=(
            _source(
                "Step input rows",
                "backend/src/intric/database/tables/flow_tables.py",
            ),
            _source(
                "Rerun operation rows",
                "backend/src/intric/database/tables/flow_tables.py",
            ),
            _source(
                "Rerun accept path",
                "backend/src/intric/flows/application/flow_run_rerun_service.py",
            ),
        ),
    ),
    _decision(
        slug="typed-lifecycle-exceptions",
        title="Typed lifecycle exceptions over HTTP-shaped lower layers",
        context="Repositories and runtime code must report state races without knowing HTTP.",
        decision="Domain exception types own lifecycle failure vocabulary below the API boundary.",
        consequences=(
            "Translate failures to Flow API errors only in application or router adapters.",
            "Reject `BadRequestException` leaks from repositories and runtime invariants.",
        ),
        source_refs=(
            _source(
                "Review checkpoint exceptions",
                "backend/src/intric/flows/domain/review_checkpoint_exceptions.py",
            ),
            _source(
                "Rerun service translation",
                "backend/src/intric/flows/application/flow_run_rerun_service.py",
            ),
        ),
    ),
    _decision(
        slug="explicit-flow-principals",
        title="Explicit Flow principals over synthetic runtime users",
        context="Runtime ownership needs to support users and service keys without fake user rows.",
        decision="`FlowPrincipal` carries the execution principal across runtime, audit, and ownership checks.",
        consequences=(
            "Reject new `UserInDB` synthesis in Flow runtime paths.",
            "Tenant-scoped repositories should receive tenant and principal fields explicitly.",
            "Review tenant filters and cross-principal denial tests together.",
        ),
        source_refs=(
            _source("Flow principal", "backend/src/intric/flows/principal.py"),
            _source(
                "Runtime actor",
                "backend/src/intric/flows/runtime/flow_run_actor.py",
            ),
            _source(
                "Run access policy",
                "backend/src/intric/flows/application/flow_run_access_policy.py",
            ),
        ),
    ),
    _decision(
        slug="authored-http-config-only",
        title="Authored HTTP config only",
        context="Legacy flat HTTP config created two input shapes for the same authored step.",
        decision="HTTP steps accept authored config with an auth block and reject legacy flat config.",
        consequences=(
            "Reject fallback reads for `body_template`, `body_json`, or flat auth fields.",
            "Keep secrets and request previews behind the authored config model.",
        ),
        source_refs=(
            _source(
                "HTTP validator",
                "backend/src/intric/flows/flow_validators_http.py",
            ),
            _source(
                "HTTP transport package",
                "backend/src/intric/flows/http_transport/__init__.py",
            ),
            _source(
                "HTTP runtime",
                "backend/src/intric/flows/runtime/http_runtime.py",
            ),
        ),
    ),
    _decision(
        slug="review-checkpoint-persistence-owner",
        title="One persistence owner for review checkpoint state",
        context="Checkpoint writes touch both the checkpoint row and parent run status.",
        decision="`FlowRunReviewCheckpointRepository` owns checkpoint persistence and locks the run first.",
        consequences=(
            "Reject checkpoint state writes through `FlowRunRepository` or ad hoc SQL.",
            "Keep run await and resume transitions in the same transaction owner.",
        ),
        source_refs=(
            _source(
                "Checkpoint repository",
                "backend/src/intric/flows/infrastructure/flow_run_review_checkpoint_repo.py",
            ),
            _source(
                "Checkpoint service",
                "backend/src/intric/flows/application/flow_run_review_checkpoint_service.py",
            ),
        ),
    ),
    _decision(
        slug="bounded-jsonb-policy",
        title="Bounded JSONB policy",
        context="Some Flow data is intentionally semi-structured, but hidden schema is technical debt.",
        decision="Every Flow JSONB column must have an owner, envelope, category, and corruption behavior.",
        consequences=(
            "Reject new Flow JSONB columns without ownership metadata and tests.",
            "Move relational candidates out of JSON when queryability or integrity requires it.",
        ),
        source_refs=(
            _source(
                "JSONB owner registry",
                "backend/src/intric/flows/infrastructure/flow_jsonb_ownership.py",
            ),
            _source(
                "Schema docs exporter",
                "backend/src/intric/flows/infrastructure/flow_schema_docs_exporter.py",
            ),
            _source(
                "Data schema docs",
                "frontend/apps/docs-site/src/content/docs/flows-for-developers/data-schema.mdx",
            ),
        ),
    ),
    _decision(
        slug="public-flow-api-error-codes",
        title="One public Flow API error-code vocabulary",
        context="API consumers need stable machine codes while users need localized recovery text.",
        decision="`FlowApiErrorCode` owns public codes and the failure taxonomy owns developer recovery detail.",
        consequences=(
            "Reject uncataloged Flow API codes and internal invariant strings in public responses.",
            "Update the failure taxonomy page when a public Flow code changes.",
        ),
        source_refs=(
            _source(
                "Error-code enum",
                "backend/src/intric/flows/flow_api_error_code.py",
            ),
            _source(
                "Failure taxonomy",
                "backend/src/intric/flows/flow_error_taxonomy.py",
            ),
            _source(
                "Developer failure page",
                "frontend/apps/docs-site/src/content/docs/flows-for-developers/when-things-fail.mdx",
            ),
        ),
    ),
    _decision(
        slug="import-boundaries",
        title="Import boundaries and Flow AI Builder isolation",
        context="Flow proper and Flow AI Builder evolve together but should not share orchestration internals.",
        decision="Import-linter blocks Flow engine imports from the AI Builder plugin boundary.",
        consequences=(
            "Reject new engine dependencies on `ai_builder` modules outside the explicit router bridge.",
            "Update package-layout docs and import-linter together when root modules move.",
        ),
        source_refs=(
            _source("Import-linter contract", "backend/.importlinter"),
            _source("Package layout", "docs/flows/package-layout.md"),
        ),
    ),
    _decision(
        slug="review-checkpoint-state-machine",
        title="Review checkpoint as a revisioned state machine",
        context="Human review is a sub-lifecycle with edits, approval, rejection, expiry, and resume.",
        decision="Review checkpoints keep their own state and revision instead of adding run statuses.",
        consequences=(
            "Reject modeling review edits as run-status transitions.",
            "Keep resume idempotency tied to checkpoint revision and decision state.",
        ),
        source_refs=(
            _source(
                "Checkpoint states",
                "backend/src/intric/flows/enums.py",
            ),
            _source(
                "Checkpoint table",
                "backend/src/intric/database/tables/flow_tables.py",
            ),
            _source(
                "Lifecycle docs",
                "frontend/apps/docs-site/src/content/docs/flows-for-developers/run-lifecycle.mdx",
            ),
        ),
    ),
    _decision(
        slug="rerun-lineage",
        title="Rerun lineage and invalidation ownership",
        context="Reruns rebuild one root step and every downstream result that depends on it.",
        decision="The rerun service plans invalidation and the rerun repository persists operation lineage.",
        consequences=(
            "Reject direct executor writes that bypass rerun operation lineage.",
            "Preserve root attempt numbers, invalidated-step rows, and request fingerprints together.",
        ),
        source_refs=(
            _source(
                "Rerun service",
                "backend/src/intric/flows/application/flow_run_rerun_service.py",
            ),
            _source(
                "Rerun repository",
                "backend/src/intric/flows/infrastructure/flow_run_rerun_repo.py",
            ),
            _source(
                "Rerun graph",
                "backend/src/intric/flows/flow_run_rerun_graph.py",
            ),
        ),
    ),
)


def validate_flow_developer_key_decisions(
    decisions: Sequence[FlowDeveloperKeyDecision] | None = None,
) -> None:
    selected_decisions = tuple(
        FLOW_DEVELOPER_KEY_DECISIONS if decisions is None else decisions
    )
    slugs = tuple(decision.slug for decision in selected_decisions)
    expected_count = len(FLOW_DEVELOPER_KEY_DECISION_SLUGS)
    if len(selected_decisions) != expected_count:
        raise ValueError(
            f"Flow key decisions must contain exactly {expected_count} decisions"
        )
    if len(set(slugs)) != len(slugs):
        raise ValueError("Flow key decisions must not contain duplicate slugs")
    if slugs != FLOW_DEVELOPER_KEY_DECISION_SLUGS:
        raise ValueError("Flow key decisions must use the required slug order")

    for decision in selected_decisions:
        _validate_slug(decision.slug)
        _validate_short_sentence(decision.slug, "context", decision.context)
        _validate_short_sentence(decision.slug, "decision", decision.decision)
        if not decision.consequences:
            raise ValueError(f"Flow key decision {decision.slug} needs consequences")
        for consequence in decision.consequences:
            _validate_short_sentence(decision.slug, "consequence", consequence)
        if not decision.source_refs:
            raise ValueError(f"Flow key decision {decision.slug} needs source refs")
        for source_ref in decision.source_refs:
            _validate_source_ref(decision.slug, source_ref)


def render_flow_developer_key_decisions_docs_page() -> str:
    validate_flow_developer_key_decisions()
    parts = [
        FLOW_DOCS_RELATED_NEXTRA_CARDS_IMPORT,
        "",
        "# Key decisions",
        "",
        "Read this page before changing a Flow boundary. It summarizes the decisions that should shape code, tests, and review.",
        "",
        "## Decision map",
        "",
        _render_decision_map(),
        "",
        "## How to read this page",
        "",
        "The refactor journal is the append-only audit trail. Code, schema, and tests are the enforceable truth. This page is the curated reviewer view for decisions that change how a new Flow reviewer should read the system.",
        "",
        "## Decisions",
        "",
        *_render_decision_cards(),
        "## Source guards",
        "",
        "- Source references are file paths only, not line-number citations.",
        "- New decisions land in the refactor journal first and promote here only when they change the architecture story.",
        "",
        "## Related",
        "",
        render_flow_docs_related_nextra_cards(
            (
                FlowDocsRelatedNextraCard(
                    "The data schema",
                    "/docs/flows-for-developers/data-schema",
                ),
                FlowDocsRelatedNextraCard(
                    "When things fail",
                    "/docs/flows-for-developers/when-things-fail",
                ),
            )
        ),
        "",
    ]
    return "\n".join(parts)


def write_flow_developer_key_decisions_docs_page(
    output_path: Path = FLOW_DEVELOPER_KEY_DECISIONS_DOCS_OUTPUT_PATH,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_flow_developer_key_decisions_docs_page(),
        encoding="utf-8",
    )


def _validate_slug(slug: str) -> None:
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        raise ValueError(f"Flow key decision slug is invalid: {slug}")


def _validate_short_sentence(slug: str, field_name: str, value: str) -> None:
    if "\n" in value or len(value) > _MAX_FIELD_LENGTH:
        raise ValueError(
            f"Flow key decision {slug} {field_name} must be one short sentence"
        )
    if len(_SENTENCE_END_PATTERN.findall(value)) != 1:
        raise ValueError(
            f"Flow key decision {slug} {field_name} must be one short sentence"
        )


def _validate_source_ref(slug: str, source_ref: FlowDecisionSourceRef) -> None:
    if ":" in source_ref.path:
        raise ValueError(
            f"Flow key decision {slug} source refs must be file paths without line numbers"
        )
    if not source_ref.path.startswith(("backend/", "docs/", "frontend/")):
        raise ValueError(
            f"Flow key decision {slug} source ref must point inside backend, docs, or frontend"
        )
    if not (REPO_ROOT / source_ref.path).is_file():
        raise ValueError(
            f"Flow key decision {slug} source file does not exist: {source_ref.path}"
        )


def _render_decision_map() -> str:
    return render_flow_docs_mermaid_block(
        "flowchart LR",
        '  data["Data model"] --> inputs["Step input files"]',
        '  data --> jsonb["JSONB policy"]',
        '  runtime["Runtime lifecycle"] --> checkpoint["Review checkpoints"]',
        '  runtime --> rerun["Rerun lineage"]',
        '  runtime --> exceptions["Typed lifecycle exceptions"]',
        '  api["API contract"] --> errors["FlowApiErrorCode"]',
        '  api --> http["Authored HTTP config"]',
        '  boundaries["Architecture boundaries"] --> imports["Import-linter"]',
        '  boundaries --> principals["FlowPrincipal"]',
    )


def _render_decision_cards() -> list[str]:
    cards: list[str] = []
    for index, decision in enumerate(FLOW_DEVELOPER_KEY_DECISIONS, start=1):
        cards.extend(
            [
                f"### {index}. {decision.title}",
                "",
                f"**Context.** {decision.context}",
                "",
                f"**Decision.** {decision.decision}",
                "",
                "**Consequences.**",
                "",
                *[f"- {consequence}" for consequence in decision.consequences],
                "",
                "**Source refs.** "
                + ", ".join(
                    f"{source_ref.label}: `{source_ref.path}`"
                    for source_ref in decision.source_refs
                )
                + ".",
                "",
            ]
        )
    return cards
