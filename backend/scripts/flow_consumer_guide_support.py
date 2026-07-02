from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Literal, get_args

from eneo.flows.api.flow_runtime_endpoint_registry import (
    FLOW_RUNTIME_ENDPOINT_CONTRACTS,
    FlowRuntimeEndpointContract,
    flow_runtime_endpoint_by_operation_id,
    flow_runtime_endpoint_by_path_field,
)
from eneo.flows.api.flow_runtime_paths import (
    FlowReviewCheckpointRuntimePathsPublic,
    FlowRuntimePathsPublic,
    build_flow_endpoint_template,
)
from eneo.flows.enums import FlowOutputMode, FlowOutputType
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_capability_manifest import (
    FINAL_OUTPUT_ARTIFACT_BY_TYPE,
    OutputArtifact,
    RuntimeInputMode,
)
from eneo.flows.flow_error_taxonomy import FLOW_ERROR_TAXONOMY
from eneo.flows.flow_run_contract_models import (
    FlowFinalOutputContractPublic,
    FlowReviewStepContractPublic,
    FlowRunContractPublic,
    FlowRuntimeInputContractPublic,
    FlowRuntimeUploadPolicyPublic,
    FormFieldPublic,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_GUIDES_DIR = (
    REPO_ROOT / "frontend" / "apps" / "docs-site" / "src" / "content" / "guides"
)
FLOW_CONSUMER_GUIDES_DIR = DOCS_GUIDES_DIR / "flows"
FLOW_CONSUMER_GUIDES_HREF = "/guides/flows"
FLOW_API_GUIDE_HREF = "/guides/flows-api-guide"
FLOW_CONSUMER_ERROR_REFERENCE_HREF = "/guides/flows/reference/errors"
CONSUMER_DOCS_API_PREFIX = "/api/v1"

MAX_TABLE_CELL_LENGTH = 240
MAX_SHORT_PARAGRAPH_LENGTH = 360
MAX_PRETTIER_INLINE_JSON_ARRAY_LENGTH = 88
CAPABILITY_MATRIX_ROW_BUDGET = 12
JSON_SCALAR_VALUE_PATTERN = r"(?:\"(?:[^\"\\]|\\.)*\"|-?\d+(?:\.\d+)?|true|false|null)"
SHORT_SCALAR_JSON_ARRAY_PATTERN = re.compile(
    rf"\[\n(?P<body>(?:\s+{JSON_SCALAR_VALUE_PATTERN},?\n)+)\s+\]"
)

GuideAudience = Literal["design", "integrate", "faq"]
NextraCalloutType = Literal["warning"]
EndpointPitfallCategory = Literal[
    "idempotency",
    "polling",
    "async_accepted",
    "artifact_retention",
    "outbound_delivery_failure",
]


@dataclass(frozen=True, slots=True)
class TestReceipt:
    file_path: str
    function_name: str


@dataclass(frozen=True, slots=True)
class EndpointSequence:
    slug: str
    title: str
    summary: str
    steps: tuple[str, ...]
    runtime_path_fields: tuple[str, ...]
    run_contract_fields: tuple[str, ...]
    receipts: tuple[TestReceipt, ...]
    error_codes: tuple[FlowApiErrorCode, ...]
    endpoint_operation_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CapabilityMatrixRow:
    input_mode: str
    output_artifact: str
    output_types: tuple[str, ...]
    output_modes: tuple[str, ...]
    notes: str


@dataclass(frozen=True, slots=True)
class EndpointPitfallRow:
    category: EndpointPitfallCategory
    capability: str
    operation_ids: tuple[str, ...]
    pitfall: str
    error_code: FlowApiErrorCode | None = None
    consumer_action: str | None = None


@dataclass(frozen=True, slots=True)
class ConsumerSectionNavEntry:
    slug: str
    title: str
    href: str
    job: str


@dataclass(frozen=True, slots=True)
class ScenarioStep:
    step: str
    input: str
    output: str
    bindings: str
    knowledge: str


@dataclass(frozen=True, slots=True)
class Scenario:
    slug: str
    title: str
    goal: str
    design_rows: tuple[ScenarioStep, ...]
    why_this_shape: str
    golden_ids: tuple[str, ...]
    receipts: tuple[TestReceipt, ...] = ()


@dataclass(frozen=True, slots=True)
class UnsupportedCallout:
    feature: str
    reason: str
    supported_alternative: str
    type: NextraCalloutType = "warning"


@dataclass(frozen=True, slots=True)
class GuideCallout:
    title: str
    body: tuple[str, ...]
    type: NextraCalloutType = "warning"


IMAGE_INPUT_UNSUPPORTED_CALLOUT = UnsupportedCallout(
    feature="Image input",
    reason="Image input is not supported by the Flow runtime today.",
    supported_alternative="Convert the image into a supported document or text input before starting the run.",
)
RUN_STATUS_WEBHOOKS_UNSUPPORTED_CALLOUT = UnsupportedCallout(
    feature="Run-status webhooks",
    reason="Eneo Flows does not expose a run-status webhook subscription surface today.",
    supported_alternative="Poll the run and step endpoints and use status capabilities to decide when polling should stop.",
)


@dataclass(frozen=True, slots=True)
class GuidePage:
    slug: str
    title: str
    purpose: str
    orientation: str
    body: tuple[str, ...]


FLOW_CONSUMER_SECTION_NAV: tuple[ConsumerSectionNavEntry, ...] = (
    ConsumerSectionNavEntry(
        slug="index",
        title="Start Here",
        href=FLOW_CONSUMER_GUIDES_HREF,
        job="Choose the right Eneo Flows consumer page for your task.",
    ),
    ConsumerSectionNavEntry(
        slug="designing-flows",
        title="Designing Flows",
        href=f"{FLOW_CONSUMER_GUIDES_HREF}/designing-flows",
        job="Design a published flow shape from supported inputs, steps, reviews, and artifacts.",
    ),
    ConsumerSectionNavEntry(
        slug="integrating-flows",
        title="Integrating Flows",
        href=f"{FLOW_CONSUMER_GUIDES_HREF}/integrating-flows",
        job="Call endpoints in the right order to create, monitor, review, rerun, and finish runs.",
    ),
    ConsumerSectionNavEntry(
        slug="flows-faq",
        title="Flows FAQ",
        href=f"{FLOW_CONSUMER_GUIDES_HREF}/flows-faq",
        job="Answer common capability and operations questions without reading the reference.",
    ),
    ConsumerSectionNavEntry(
        slug="reference",
        title="Reference",
        href=FLOW_CONSUMER_ERROR_REFERENCE_HREF,
        job="Look up Flow error handling.",
    ),
)


def output_path_for(slug: str) -> Path:
    return FLOW_CONSUMER_GUIDES_DIR / f"{slug}.mdx"


def render_json_example(value: object) -> str:
    rendered = json.dumps(value, indent=2)
    return SHORT_SCALAR_JSON_ARRAY_PATTERN.sub(_inline_short_json_array, rendered)


def _inline_short_json_array(match: re.Match[str]) -> str:
    values = [
        line.strip().removesuffix(",")
        for line in match.group("body").splitlines()
        if line.strip()
    ]
    inline = "[" + ", ".join(values) + "]"
    # Keep generated examples stable with the docs-site Prettier check.
    if len(inline) > MAX_PRETTIER_INLINE_JSON_ARRAY_LENGTH:
        return match.group(0)
    return inline


def runtime_path_field_names() -> set[str]:
    return set(FlowRuntimePathsPublic.model_fields) | {
        f"review_checkpoints.{field}"
        for field in FlowReviewCheckpointRuntimePathsPublic.model_fields
    }


def run_contract_field_names() -> set[str]:
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


def validate_endpoint_sequences(sequences: Sequence[EndpointSequence]) -> None:
    runtime_fields = runtime_path_field_names()
    endpoint_by_operation_id = flow_runtime_endpoint_by_operation_id()
    contract_fields = run_contract_field_names()
    if not sequences:
        raise ValueError("Consumer guide must define endpoint sequences")
    for sequence in sequences:
        _require_slug(sequence.slug, "endpoint sequence")
        _require_short_text(sequence.title, f"{sequence.slug} title")
        _require_short_text(sequence.summary, f"{sequence.slug} summary")
        if not sequence.steps:
            raise ValueError(f"{sequence.slug} needs endpoint steps")
        if not sequence.runtime_path_fields and not sequence.run_contract_fields:
            raise ValueError(f"{sequence.slug} needs path or contract fields")
        unknown_runtime = set(sequence.runtime_path_fields) - runtime_fields
        if unknown_runtime:
            raise ValueError(
                f"{sequence.slug} uses unknown runtime path fields: "
                f"{sorted(unknown_runtime)}"
            )
        unowned_runtime = {
            field
            for field in sequence.runtime_path_fields
            if tuple(field.split(".")) not in flow_runtime_endpoint_by_path_field()
        }
        if unowned_runtime:
            raise ValueError(
                f"{sequence.slug} uses runtime path fields without endpoint ownership: "
                f"{sorted(unowned_runtime)}"
            )
        unknown_endpoint_operations = (
            set(sequence.endpoint_operation_ids) - endpoint_by_operation_id.keys()
        )
        if unknown_endpoint_operations:
            raise ValueError(
                f"{sequence.slug} uses unknown endpoint operation ids: "
                f"{sorted(unknown_endpoint_operations)}"
            )
        unknown_contract = set(sequence.run_contract_fields) - contract_fields
        if unknown_contract:
            raise ValueError(
                f"{sequence.slug} uses unknown run contract fields: "
                f"{sorted(unknown_contract)}"
            )
        if not sequence.receipts:
            raise ValueError(f"{sequence.slug} needs at least one test receipt")
        if not sequence.error_codes:
            raise ValueError(f"{sequence.slug} needs handled error codes")
        _validate_receipts(sequence.receipts, sequence.slug)
        for step in sequence.steps:
            _require_short_text(step, f"{sequence.slug} step")


def validate_capability_matrix(
    rows: Sequence[CapabilityMatrixRow], budget: int
) -> None:
    allowed_modes = set(get_args(RuntimeInputMode))
    allowed_artifacts = set(get_args(OutputArtifact))
    expected_artifacts = set(FINAL_OUTPUT_ARTIFACT_BY_TYPE.values())
    if not rows:
        raise ValueError("Consumer guide capability matrix must define rows")
    if len(rows) > budget:
        raise ValueError(
            f"Consumer guide capability matrix has {len(rows)} rows; budget is {budget}"
        )
    if {row.output_artifact for row in rows} != expected_artifacts:
        raise ValueError("Consumer guide capability matrix must cover each artifact")
    for row in rows:
        if row.input_mode not in allowed_modes:
            raise ValueError(f"Unknown runtime input mode: {row.input_mode}")
        if row.output_artifact not in allowed_artifacts:
            raise ValueError(f"Unknown output artifact: {row.output_artifact}")
        if not row.output_types:
            raise ValueError(f"{row.output_artifact} needs output types")
        if not row.output_modes:
            raise ValueError(f"{row.output_artifact} needs output modes")
        for output_type in row.output_types:
            FlowOutputType(output_type)
        for output_mode in row.output_modes:
            FlowOutputMode(output_mode)
        _require_short_text(row.notes, f"{row.output_artifact} notes")


def validate_endpoint_pitfall_rows(rows: Sequence[EndpointPitfallRow]) -> None:
    if not rows:
        raise ValueError("Consumer endpoint pitfall matrix must define rows")
    required_categories = set(get_args(EndpointPitfallCategory))
    categories = {row.category for row in rows}
    if categories != required_categories:
        raise ValueError(
            "Consumer endpoint pitfall matrix category drift: "
            f"missing={sorted(required_categories - categories)}; "
            f"stale={sorted(categories - required_categories)}"
        )
    endpoint_by_operation_id = flow_runtime_endpoint_by_operation_id()
    async_operation_ids = async_accepted_operation_ids()
    for row in rows:
        _require_table_cell(row.capability, f"{row.category} capability")
        _require_table_cell(row.pitfall, f"{row.category} pitfall")
        if not row.operation_ids:
            raise ValueError(f"{row.category} needs at least one operation id")
        unknown_operation_ids = set(row.operation_ids) - endpoint_by_operation_id.keys()
        if unknown_operation_ids:
            raise ValueError(
                f"{row.category} uses unknown operation ids: "
                f"{sorted(unknown_operation_ids)}"
            )
        if (
            row.category == "async_accepted"
            and row.operation_ids != async_operation_ids
        ):
            raise ValueError(
                "async_accepted pitfall row must derive operation ids from "
                "HTTP 202 runtime endpoint contracts"
            )
        if row.error_code is None:
            if row.consumer_action is None:
                raise ValueError(
                    f"{row.category} needs consumer_action when no error_code is set"
                )
            _require_table_cell(row.consumer_action, f"{row.category} consumer action")
        else:
            if row.consumer_action is not None:
                raise ValueError(
                    f"{row.category} must derive consumer_action from taxonomy"
                )
            _require_table_cell(
                endpoint_pitfall_consumer_action(row),
                f"{row.category} taxonomy consumer action",
            )


def async_accepted_operation_ids() -> tuple[str, ...]:
    return tuple(
        contract.operation_id
        for contract in FLOW_RUNTIME_ENDPOINT_CONTRACTS
        if contract.success_status == 202
    )


def endpoint_pitfall_consumer_action(row: EndpointPitfallRow) -> str:
    if row.error_code is not None:
        return FLOW_ERROR_TAXONOMY[row.error_code].consumer_action
    if row.consumer_action is None:
        raise ValueError(f"{row.category} needs consumer_action")
    return row.consumer_action


def validate_scenarios(scenarios: Sequence[Scenario]) -> None:
    if not scenarios:
        raise ValueError("Consumer guide must define scenarios")
    for scenario in scenarios:
        _require_slug(scenario.slug, "scenario")
        _require_short_text(scenario.title, f"{scenario.slug} title")
        _require_short_text(scenario.goal, f"{scenario.slug} goal")
        _require_short_text(
            scenario.why_this_shape,
            f"{scenario.slug} why_this_shape",
            max_length=420,
        )
        if not scenario.design_rows:
            raise ValueError(f"{scenario.slug} needs design rows")
        if not scenario.golden_ids:
            raise ValueError(f"{scenario.slug} needs golden ids")
        _validate_receipts(scenario.receipts, scenario.slug)
        for row in scenario.design_rows:
            _require_table_cell(row.step, f"{scenario.slug} step")
            _require_table_cell(row.input, f"{scenario.slug} input")
            _require_table_cell(row.output, f"{scenario.slug} output")
            _require_table_cell(row.bindings, f"{scenario.slug} bindings")
            _require_table_cell(row.knowledge, f"{scenario.slug} knowledge")


def validate_unsupported_callouts(callouts: Sequence[UnsupportedCallout]) -> None:
    if not callouts:
        raise ValueError("Consumer guide must define unsupported callouts")
    for callout in callouts:
        _require_component_safe_text(callout.feature, "unsupported feature")
        _require_short_text(callout.feature, "unsupported feature")
        _require_component_safe_text(callout.reason, f"{callout.feature} reason")
        _require_short_text(callout.reason, f"{callout.feature} reason")
        _require_component_safe_text(
            callout.supported_alternative,
            f"{callout.feature} supported alternative",
        )
        _require_short_text(
            callout.supported_alternative,
            f"{callout.feature} supported alternative",
        )
        validate_guide_callout(_guide_callout_for_unsupported(callout))


def validate_guide_callouts(callouts: Sequence[GuideCallout]) -> None:
    if not callouts:
        raise ValueError("Consumer guide must define callouts")
    for callout in callouts:
        validate_guide_callout(callout)


def validate_guide_callout(callout: GuideCallout) -> None:
    _require_component_safe_text(callout.title, "callout title")
    _require_short_text(callout.title, "callout title")
    if callout.type != "warning":
        raise ValueError("Consumer guide callouts must use warning type")
    if not callout.body:
        raise ValueError(f"{callout.title} needs callout body")
    for index, line in enumerate(callout.body, start=1):
        _require_component_safe_text(line, f"{callout.title} body line {index}")
        _require_short_text(line, f"{callout.title} body line {index}")


def validate_consumer_section_nav(
    entries: Sequence[ConsumerSectionNavEntry] = FLOW_CONSUMER_SECTION_NAV,
) -> None:
    if not entries:
        raise ValueError("Consumer section nav must define entries")
    slugs = [entry.slug for entry in entries]
    if len(slugs) != len(set(slugs)):
        raise ValueError("Consumer section nav slugs must be unique")
    if slugs != [
        "index",
        "designing-flows",
        "integrating-flows",
        "flows-faq",
        "reference",
    ]:
        raise ValueError("Consumer section nav order changed")
    for entry in entries:
        _require_slug(entry.slug, "consumer section nav")
        _require_short_text(entry.title, f"{entry.slug} title")
        _require_short_text(entry.job, f"{entry.slug} job")
        if not entry.href.startswith(FLOW_CONSUMER_GUIDES_HREF):
            raise ValueError(f"{entry.slug} href must stay in the Flow guides section")


def validate_json_examples(examples: Sequence[str]) -> None:
    for index, example in enumerate(examples, start=1):
        try:
            json.loads(example)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Consumer guide JSON example {index} is invalid: {exc}")


def render_page(page: GuidePage) -> str:
    validate_guide_page(page)
    imports = _nextra_component_imports(page.body)
    body = _trim_trailing_blank_lines(page.body)
    lines = [
        *imports,
        *(("",) if imports else ()),
        f"# {page.title}",
        "",
        page.purpose,
        "",
        page.orientation,
        "",
        *body,
        "",
        _next_line_for_page(page.slug),
    ]
    return "\n".join(lines).rstrip() + "\n"


def _trim_trailing_blank_lines(lines: Sequence[str]) -> tuple[str, ...]:
    trimmed = list(lines)
    while trimmed and not trimmed[-1]:
        trimmed.pop()
    return tuple(trimmed)


def validate_guide_page(page: GuidePage) -> None:
    _require_slug(page.slug, "guide page")
    _require_short_text(page.title, f"{page.slug} title")
    _require_page_prose(page.purpose, f"{page.slug} purpose")
    _require_page_prose(page.orientation, f"{page.slug} orientation")
    _next_line_for_page(page.slug)


def _nextra_component_imports(body: Sequence[str]) -> tuple[str, ...]:
    page = "\n".join(body)
    imports: list[str] = []
    if "<Callout " in page:
        imports.append('import { Callout } from "nextra/components";')
    return tuple(imports)


def _next_line_for_page(slug: str) -> str:
    entries = list(FLOW_CONSUMER_SECTION_NAV)
    slugs = [entry.slug for entry in entries]
    if slug not in slugs:
        raise ValueError(f"{slug} is not in the consumer section nav")
    index = slugs.index(slug)
    if index >= len(entries) - 1:
        raise ValueError(f"{slug} must have a next consumer section nav entry")
    next_entry = entries[index + 1]
    return f"Next: [{next_entry.title}]({next_entry.href})."


def render_endpoint_sequence(sequence: EndpointSequence) -> str:
    endpoint_contracts = endpoint_contracts_for_sequence(sequence)
    lines = [
        f"### {sequence.title}",
        "",
        sequence.summary,
        "",
        *[f"{index}. {step}" for index, step in enumerate(sequence.steps, start=1)],
        "",
        "Endpoint facts:",
        "",
        render_endpoint_contract_table(endpoint_contracts),
        "",
        "Contract coverage: These endpoints are contract-tested.",
        "",
        "Errors you must handle: "
        + ", ".join(f"`{code.value}`" for code in sequence.error_codes)
        + ".",
    ]
    return "\n".join(lines)


def endpoint_contracts_for_sequence(
    sequence: EndpointSequence,
) -> tuple[FlowRuntimeEndpointContract, ...]:
    endpoint_by_field = flow_runtime_endpoint_by_path_field()
    endpoint_by_operation = flow_runtime_endpoint_by_operation_id()
    contracts: list[FlowRuntimeEndpointContract] = []
    seen_operation_ids: set[str] = set()

    for runtime_path_field in sequence.runtime_path_fields:
        contract = endpoint_by_field[tuple(runtime_path_field.split("."))]
        if contract.operation_id not in seen_operation_ids:
            contracts.append(contract)
            seen_operation_ids.add(contract.operation_id)

    for operation_id in sequence.endpoint_operation_ids:
        contract = endpoint_by_operation[operation_id]
        if contract.operation_id not in seen_operation_ids:
            contracts.append(contract)
            seen_operation_ids.add(contract.operation_id)

    return tuple(contracts)


def documented_consumer_operation_ids(
    *,
    sequences: Sequence[EndpointSequence],
    worked_example_operation_ids: Sequence[str] = (),
    pitfall_rows: Sequence[EndpointPitfallRow] = (),
) -> set[str]:
    documented = set(worked_example_operation_ids)
    for sequence in sequences:
        documented.update(
            contract.operation_id
            for contract in endpoint_contracts_for_sequence(sequence)
        )
    for row in pitfall_rows:
        documented.update(row.operation_ids)
    return documented


def render_endpoint_contract_table(
    contracts: Sequence[FlowRuntimeEndpointContract],
) -> str:
    return render_markdown_table(
        ("Endpoint", "Method", "Success", "Operation"),
        tuple(
            (
                f"`{build_flow_endpoint_template(contract.route_path, api_prefix=CONSUMER_DOCS_API_PREFIX)}`",
                f"`{contract.method.upper()}`",
                f"`{success_status_label(contract.success_status)}`",
                f"`{contract.operation_id}`",
            )
            for contract in contracts
        ),
    )


def render_endpoint_pitfall_matrix(rows: Sequence[EndpointPitfallRow]) -> str:
    validate_endpoint_pitfall_rows(rows)
    return render_markdown_table(
        ("What you can do", "Endpoint owner", "Trap", "Consumer action"),
        tuple(
            (
                row.capability,
                _render_endpoint_pitfall_operation_cell(row.operation_ids),
                row.pitfall,
                endpoint_pitfall_consumer_action(row),
            )
            for row in rows
        ),
    )


def _render_endpoint_pitfall_operation_cell(operation_ids: Sequence[str]) -> str:
    endpoint_by_operation_id = flow_runtime_endpoint_by_operation_id()
    return "; ".join(
        (
            f"`{contract.method.upper()} {contract.operation_id}` "
            f"(`{success_status_label(contract.success_status)}`)"
        )
        for contract in (
            endpoint_by_operation_id[operation_id] for operation_id in operation_ids
        )
    )


def success_status_label(status_code: int) -> str:
    try:
        phrase = HTTPStatus(status_code).phrase
    except ValueError:
        return str(status_code)
    return f"{status_code} {phrase}"


def render_unsupported_callout(callout: UnsupportedCallout) -> str:
    return render_callout(_guide_callout_for_unsupported(callout))


def render_callout(callout: GuideCallout) -> str:
    validate_guide_callout(callout)
    return "\n".join(
        [
            f'<Callout type="{callout.type}">',
            "",
            f"**{callout.title}.**",
            "",
            *_render_callout_body(callout.body),
            "",
            "</Callout>",
        ]
    )


def _render_callout_body(body: Sequence[str]) -> tuple[str, ...]:
    lines: list[str] = []
    for index, line in enumerate(body):
        if index > 0:
            lines.append("")
        lines.append(line)
    return tuple(lines)


def _guide_callout_for_unsupported(callout: UnsupportedCallout) -> GuideCallout:
    return GuideCallout(
        title=f"Not supported: {callout.feature}",
        body=(
            callout.reason,
            f"Closest supported alternative: {callout.supported_alternative}",
        ),
        type=callout.type,
    )


def render_scenario(scenario: Scenario) -> str:
    return "\n".join(
        [
            f"### {scenario.title}",
            "",
            f"Goal: {scenario.goal}",
            "",
            render_markdown_table(
                ("Step", "Input", "Output", "Bindings", "Knowledge"),
                tuple(
                    (row.step, row.input, row.output, row.bindings, row.knowledge)
                    for row in scenario.design_rows
                ),
            ),
            "",
            scenario.why_this_shape,
            "",
            "Build coverage: This scenario is covered by the Flow AI Builder golden matrix.",
        ]
    )


def render_markdown_table(
    headers: tuple[str, ...], rows: tuple[tuple[str, ...], ...]
) -> str:
    for cell in (*headers, *(cell for row in rows for cell in row)):
        _require_table_cell(cell, "table cell")
    widths = tuple(
        max(len(row[index]) for row in (headers, *rows))
        for index in range(len(headers))
    )

    def render_row(cells: tuple[str, ...]) -> str:
        return (
            "| "
            + " | ".join(
                cell.ljust(width) for cell, width in zip(cells, widths, strict=True)
            )
            + " |"
        )

    separator = tuple("-" * max(3, width) for width in widths)
    return "\n".join(
        [render_row(headers), render_row(separator), *map(render_row, rows)]
    )


def write_page(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _validate_receipts(receipts: Sequence[TestReceipt], owner: str) -> None:
    for receipt in receipts:
        if not receipt.file_path.startswith("backend/tests/"):
            raise ValueError(f"{owner} receipt must point at backend/tests")
        if not receipt.function_name.startswith("test_"):
            raise ValueError(f"{owner} receipt must name a pytest test function")
        test_file = REPO_ROOT / receipt.file_path
        if not test_file.is_file():
            raise ValueError(
                f"{owner} receipt file does not exist: {receipt.file_path}"
            )
        if f"def {receipt.function_name}" not in test_file.read_text(encoding="utf-8"):
            raise ValueError(
                f"{owner} receipt function does not exist: {receipt.function_name}"
            )


def _require_slug(value: str, label: str) -> None:
    if not value or value.strip() != value or " " in value:
        raise ValueError(f"{label} slug must be non-empty and space-free")


def _require_short_text(
    value: str,
    label: str,
    *,
    max_length: int = MAX_SHORT_PARAGRAPH_LENGTH,
) -> None:
    if not value.strip():
        raise ValueError(f"{label} must not be empty")
    if "\n" in value or len(value) > max_length:
        raise ValueError(f"{label} must be one short sentence")
    if "|" in value:
        raise ValueError(f"{label} must not contain table pipes")


def _require_page_prose(value: str, label: str) -> None:
    _require_short_text(value, label)
    _require_component_safe_text(value, label)
    if "Read this when" in value or "After reading you can" in value:
        raise ValueError(f"{label} must not use the old generated header")


def _require_component_safe_text(value: str, label: str) -> None:
    if "{" in value or "<" in value:
        raise ValueError(f"{label} must be JSX-safe")


def _require_table_cell(value: str, label: str) -> None:
    if not value.strip():
        raise ValueError(f"{label} must not be empty")
    if "\n" in value or len(value) > MAX_TABLE_CELL_LENGTH:
        raise ValueError(f"{label} must be short table text")
    if "|" in value:
        raise ValueError(f"{label} must not contain table pipes")
