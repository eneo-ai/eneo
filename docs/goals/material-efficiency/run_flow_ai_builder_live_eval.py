#!/usr/bin/env python3
"""Live smoke/eval runner for Flow AI Builder material-efficiency cases."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

DEFAULT_API_BASE = "http://localhost:8123"
DEFAULT_OUTPUT_ROOT = Path("/tmp/material-efficiency-live-eval")
DEFAULT_STATE_PATH = Path(__file__).with_name(
    "flow-ai-builder-material-efficiency-state.yaml"
)
JsonObject = dict[str, Any]
JsonList = list[Any]

SCORE_AXES = [
    "clarification_restraint",
    "minimal_viable_topology",
    "source_preservation",
    "targeted_material_routing",
    "form_field_lifecycle",
    "terminal_mode_fit",
    "context_efficiency",
    "output_usefulness",
]


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    prompt: str
    tags: list[str]
    desired_signal: str
    failure_signal: str
    suite: str = "create"
    notes: str | None = None


@dataclass
class CaseRunResult:
    case_id: str
    run_no: int
    suite: str
    space_id: str
    status: str
    session_id: str | None = None
    plan_id: str | None = None
    flow_id: str | None = None
    output_dir: str | None = None
    error: str | None = None
    requirements_version: str | None = None
    checkpoints: list[str] = field(default_factory=lambda: [])
    builder_errors: list[str] = field(default_factory=lambda: [])
    review_required: bool = True
    score_axes: dict[str, int | None] = field(
        default_factory=lambda: {axis: None for axis in SCORE_AXES}
    )
    metrics: dict[str, int | None] = field(
        default_factory=lambda: {
            "binding_bytes": None,
            "fan_in_width": None,
            "structured_field_count": None,
            "whole_output_reference_count": None,
            "source_duplication_count": None,
            "all_previous_steps_count": None,
        }
    )
    metrics_implementation: str = "manual_review_required"


CREATE_CASES: list[EvalCase] = [
    EvalCase(
        case_id="V1",
        prompt="Jag vill kunna ladda upp ett dokument och få en kort sammanfattning.",
        tags=[
            "create_path",
            "document_to_text",
            "minimal_topology",
            "null_form_fields",
        ],
        desired_signal=(
            "A one-step document-to-text flow or one concise clarification about "
            "output format. No invented fields, artifact terminal, or unnecessary JSON."
        ),
        failure_signal=(
            "The user receives a heavier flow than requested, extra setup questions, "
            "unused fields, or a document/PDF output for a short text summary."
        ),
    ),
    EvalCase(
        case_id="V2",
        prompt="Jag vill spela in ett möte och få ut en rapport i Word.",
        tags=[
            "create_path",
            "audio_to_docx_create",
            "transcript_preservation",
            "structured_summary",
        ],
        desired_signal=(
            "A small audio-to-Word plan. If structured meeting sections are introduced, "
            "the Word step can see both transcript and selected section outputs."
        ),
        failure_signal=(
            "The Word report omits meeting content, only reflects the final extraction "
            "step, or produces text instead of a Word artifact."
        ),
    ),
    EvalCase(
        case_id="V3",
        prompt="Jag har flera filer och vill få hjälp att gå igenom dem.",
        tags=[
            "create_path",
            "vague_multi_file",
            "clarification",
            "avoid_premature_fan_in",
        ],
        desired_signal=(
            "Asks whether the user wants summary, comparison, extraction, contradiction "
            "search, translation, or a final document before committing to topology."
        ),
        failure_signal=(
            "Assumes a comparison/report workflow before the user chooses one, or builds "
            "a broad context-heavy flow for an unresolved request."
        ),
    ),
    EvalCase(
        case_id="V4",
        prompt="Jag vill skapa ett dokument som följer en mall.",
        tags=[
            "create_path",
            "docx_create_vs_template_fill",
            "clarification",
            "terminal_mode",
        ],
        desired_signal=(
            "Asks whether the user has a DOCX template with placeholders or wants a "
            "generated document structure. The terminal mode matches the answer."
        ),
        failure_signal=(
            "Silently chooses generated document or template-fill workflow, then produces "
            "an artifact that cannot match the real template situation."
        ),
    ),
    EvalCase(
        case_id="V5",
        prompt=(
            "Jag vill att flödet ska läsa ett dokument, plocka ut viktiga uppgifter "
            "och skicka resultatet till vårt API."
        ),
        tags=[
            "create_path",
            "document_to_structured",
            "http_post_call",
            "api_body_binding",
        ],
        desired_signal=(
            "Asks for endpoint, auth, and body schema if not supplied. API call body is "
            "built from prepared extracted fields, not raw full document material."
        ),
        failure_signal=(
            "Posts incomplete/raw material, invents API details, creates an unrelated "
            "report artifact, or cannot explain which extracted values reach the body."
        ),
        notes=(
            "HTTP output may not be authorable through the current create materializer; "
            "score as capability discovery if apply fails for unsupported http_post."
        ),
    ),
    EvalCase(
        case_id="C1",
        prompt=(
            "Bygg ett flöde där användaren spelar in eller laddar upp ett möte. Steg 1 "
            "ska transkribera ljudet. Därefter ska flödet skapa separata JSON-underlag "
            "för rubrikerna Sammanfattning, Beslut, Åtgärder, Risker, Närvaro, "
            "Uppföljning, Citat, Avvikelser, Frågor till nästa möte och Övrigt. "
            "Slutsteget ska producera en Word-rapport. Slutsteget får inte läsa hela "
            "tidigare innehållet, utan ska väva in varje rubrik via explicita "
            "fältreferenser till respektive JSON-steg och ska också ha tillgång till "
            "transkriptionen som källmaterial där det behövs. Inmatningsfält behövs inte."
        ),
        tags=[
            "create_path",
            "audio_to_structured_sections",
            "underlag_till_text",
            "docx_create",
            "wide_targeted_fan_in",
        ],
        desired_signal=(
            "Every section extractor that needs the transcript has it, and the Word "
            "report receives section fields plus source context where needed."
        ),
        failure_signal=(
            "Final report is empty, generic, missing sections, disconnected from the "
            "transcript, or only reflects the last intermediate output."
        ),
    ),
    EvalCase(
        case_id="C2",
        prompt=(
            "Användaren laddar upp en lång PDF-rapport. Innan körning ska användaren "
            "ange organisationsnamn, rapportperiod och fokusområde som inmatningsfält. "
            "Flödet ska skapa fyra strukturerade JSON-underlag: Bakgrund, Resultat, "
            "Risker och Slutsatser. Fokusområde ska styra riskanalysen redan i "
            "risksteget, inte bara i slutrapporten. Slutligen ska en PDF-rapport skrivas "
            "där organisationsnamn och rapportperiod används i rapportens rubriker och "
            "där varje rapportdel byggs från explicita JSON-fält."
        ),
        tags=[
            "create_path",
            "document_to_structured_sections",
            "form_fields_to_intermediate_step",
            "pdf_create",
        ],
        desired_signal=(
            "Organisationsnamn and rapportperiod shape final report, while fokusområde "
            "reaches risk analysis before final report."
        ),
        failure_signal=(
            "Focus only appears in final styling, fields are unused, PDF lacks requested "
            "headings, or source document disappears after first JSON step."
        ),
    ),
    EvalCase(
        case_id="C3",
        prompt=(
            "Användaren laddar upp 2-5 underlagsfiler. Flödet ska extrahera nyckelfakta "
            "som strukturerad JSON från varje fil eller från varje dokumentdel, sedan "
            "identifiera motsägelser mellan källorna i ett separat analyssteg, och "
            "slutligen skriva en sammanställning där fakta och motsägelser presenteras "
            "tydligt. Här är bred fan-in tillåten i motsägelseanalysen eftersom uppgiften "
            "är jämförelse, men slutrapporten ska ändå använda den sammanställda "
            "jämförelseanalysen och relevanta strukturerade fält i stället för att "
            "okritiskt dumpa allt råmaterial."
        ),
        tags=[
            "create_path",
            "multi_document_compare",
            "legitimate_broad_fan_in",
            "structured_final",
        ],
        desired_signal=(
            "Broad access is limited to the justified comparison step. Final report uses "
            "comparison result and selected facts rather than rereading every raw source."
        ),
        failure_signal=(
            "Comparison cannot see all sources, source distinctions are lost, or every "
            "later step receives every raw document without need."
        ),
    ),
    EvalCase(
        case_id="C4",
        prompt=(
            "Fyll i en uppladdad Word-mall som innehåller {{platshållare}}. Användaren "
            "laddar upp ett underlagsdokument och fyller i inmatningsfälten referens_id "
            "och ansvarig innan körning. Steg 1 ska extrahera strukturerad JSON ur "
            "underlaget. Steg 2 ska kombinera den extraherade JSON:en med referens_id "
            "och ansvarig till en sammanställning som matchar mallens platshållare. "
            "Steg 3 ska fylla mallen från sammanställningen - inte direkt från "
            "råunderlaget och inte genom lösa hårdkodade variabler."
        ),
        tags=[
            "create_path",
            "document_to_docx_template",
            "form_fields_to_template_material",
            "prepared_mapping",
        ],
        desired_signal=(
            "Template filling is terminal and receives a prepared placeholder mapping "
            "built from extracted fields plus referens_id and ansvarig."
        ),
        failure_signal=(
            "Template output is missing placeholders, form values are unused, examples "
            "are hard-coded, or raw source text is sent directly to the template."
        ),
    ),
    EvalCase(
        case_id="C5",
        prompt=(
            "Bygg ett flöde där användaren spelar in eller laddar upp ett kundsamtal. "
            "Innan körning ska användaren ange ticket_id, kundnamn och önskad rapportton "
            "som inmatningsfält. Flödet ska: 1) transkribera ljudet, 2) extrahera beslut "
            "och åtgärder per agendapunkt för fyra agendapunkter som separata "
            "JSON-underlag, 3) skriva ett första Word-utkast som väver in ticket_id, "
            "kundnamn och de fyra JSON-underlagen, 4) kritisera utkastet i ett separat "
            "steg utifrån täckning, ton och saknade beslut, 5) revidera utkastet till "
            "en slutgiltig Word-rapport baserat på både utkastet och kritiken. "
            "Rapportton ska styra utkast och revision, men den ska inte ersätta "
            "källmaterialet."
        ),
        tags=[
            "create_path",
            "audio_to_structured_sections",
            "multi_step_quality_chain",
            "form_fields_to_draft_and_revision",
            "docx_create",
        ],
        desired_signal=(
            "Transcript, agenda JSON, ticket metadata, draft, critique, and revision "
            "reach only the steps that need them."
        ),
        failure_signal=(
            "Critique and revision collapse into one step, final report only reflects "
            "critique, ticket metadata disappears, tone overrides facts, or source "
            "material is unavailable to extraction steps."
        ),
    ),
]

SUPPLEMENTAL_CASES: list[EvalCase] = [
    EvalCase(
        case_id="E1",
        suite="edit",
        prompt=(
            "Lägg till ett separat granskningssteg före Word-rapporten som kontrollerar "
            "om varje rubrik har underlag. Slutrapporten ska använda granskningen utan "
            "att tappa transkription eller JSON-underlag."
        ),
        tags=["edit_path", "source_preservation", "review_step"],
        desired_signal="The edit preserves existing transcript/section routing and adds only needed review material.",
        failure_signal="The edit breaks existing source/section routing or rewrites the flow unnecessarily.",
        notes="Requires --edit-flow-id or a flow created from C1.",
    ),
    EvalCase(
        case_id="E2",
        suite="edit",
        prompt=(
            "Ändra så att mallen fortfarande fylls, men lägg till ett kvalitetssäkringssteg "
            "som kontrollerar att referens_id, ansvarig och alla mallfält är ifyllda innan "
            "mallen skapas."
        ),
        tags=["edit_path", "template_fill", "form_field_lifecycle"],
        desired_signal="Template-fill remains terminal and form-field/material routing survives the inserted step.",
        failure_signal="Template-fill stops being terminal, fields disappear, or raw source replaces prepared mapping.",
        notes="Requires --edit-flow-id or a flow created from C4.",
    ),
    EvalCase(
        case_id="H1",
        suite="capability",
        prompt=(
            "Skapa ett flöde där användaren anger kundnummer som inmatningsfält. Flödet "
            "ska hämta kundmetadata från ett GET-anrop, läsa ett uppladdat ärendedokument, "
            "extrahera beslut som JSON och POST:a en sammanfattning till ett callback-API. "
            "Kundnummer ska användas i GET-steget och metadata från GET-steget ska användas "
            "i POST-body tillsammans med extraherad JSON."
        ),
        tags=[
            "http_get_call",
            "http_post_call",
            "api_body_binding",
            "capability_check",
        ],
        desired_signal="API material is routed through explicit fields; GET response and document extraction reach POST body.",
        failure_signal="API details are invented, raw dumps are posted, or the builder cannot author the requested HTTP path.",
        notes=(
            "Engine supports http_get/http_post, but current AI Builder create materializer "
            "rejects http_post. Treat this as capability-discovery evidence unless fixed."
        ),
    ),
    EvalCase(
        case_id="H2",
        suite="capability",
        prompt=(
            "Skapa ett flöde där användaren anger artikelnummer som inmatningsfält och "
            "laddar upp en produktbeskrivning. Flödet ska hämta aktuell produktmetadata "
            "via GET, sammanfatta produktbeskrivningen och skriva ett kort internt svar "
            "som använder både hämtad metadata och sammanfattningen. Artikelnummer ska "
            "användas i GET-steget, inte bara nämnas i sluttexten."
        ),
        tags=[
            "http_get_call",
            "document_summary",
            "material_merge",
            "capability_check",
        ],
        desired_signal="GET call is material-producing, and final answer uses API metadata plus source summary.",
        failure_signal="Article number is only mentioned in final text, or API metadata never becomes step material.",
        notes="Treat as capability-discovery evidence if AI Builder cannot author http_get input sources.",
    ),
    EvalCase(
        case_id="N1",
        suite="restraint",
        prompt="Översätt den här meningen till engelska: Vi ses på mötet imorgon.",
        tags=["restraint", "null_control", "minimal_topology"],
        desired_signal=(
            "Score 2 only if the builder questions whether a reusable flow is needed or "
            "proposes one text-to-text step with no form fields and no JSON."
        ),
        failure_signal="Adds document, JSON, artifact terminal, form fields, or a multi-step workflow.",
    ),
    EvalCase(
        case_id="Q1",
        suite="quality_chain_basic",
        prompt=(
            "Skapa ett enkelt textflöde som skriver ett kort svar på en inkommande fråga, "
            "låter ett separat kritiksteg kontrollera tydlighet och saklighet, och skriver "
            "en slutversion som använder kritiken. Inga filer och inga inmatningsfält behövs."
        ),
        tags=["multi_step_quality_chain", "basic", "text_to_text"],
        desired_signal="Draft, critique, and final revision are separate and only pass needed text forward.",
        failure_signal="Critique is skipped, merged into one prompt, or final step loses the draft/critique relationship.",
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Flow AI Builder material-efficiency live smoke/eval cases."
    )
    parser.add_argument(
        "--api-base", default=os.getenv("ENEO_LOCAL_API_BASE", DEFAULT_API_BASE)
    )
    parser.add_argument("--api-key", default=os.getenv("ENEO_LOCAL_API_KEY"))
    parser.add_argument("--output-dir", type=Path, default=default_output_dir())
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument(
        "--baseline-label",
        default=None,
        help="Also write summary to /tmp/material-efficiency-live-eval/baselines/<label>/summary.json.",
    )
    parser.add_argument(
        "--smoke", action="store_true", help="Run sessions and flow-list smoke checks."
    )
    parser.add_argument(
        "--list-cases", action="store_true", help="Print available cases and exit."
    )
    parser.add_argument(
        "--case", action="append", dest="case_ids", help="Case ID to run. Repeatable."
    )
    parser.add_argument("--all", action="store_true", help="Run all create cases.")
    parser.add_argument(
        "--include-supplemental",
        action="store_true",
        help="Include edit, HTTP capability, restraint, and basic quality-chain probes.",
    )
    parser.add_argument("--runs", type=int, default=1, help="Number of runs per case.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Approve/apply generated plans. Default stops after plan inspection.",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Publish applied flows after inspection. Requires --apply.",
    )
    parser.add_argument(
        "--edit-flow-id",
        default=None,
        help="Existing flow ID for supplemental edit-path cases.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=240,
        help="HTTP timeout seconds for message/SSE calls.",
    )
    return parser.parse_args()


class ApiClient:
    def __init__(self, base_url: str, api_key: str, timeout: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def get_json(self, path: str) -> Any:
        return self._request_json("GET", path)

    def post_json(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        return self._request_json("POST", path, payload)

    def post_stream(self, path: str, payload: dict[str, Any]) -> bytes:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            method="POST",
            headers={
                "accept": "text/event-stream",
                "content-type": "application/json",
                "X-API-Key": self.api_key,
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return response.read()

    def _request_json(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> Any:
        data = None
        headers = {"accept": "application/json", "X-API-Key": self.api_key}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["content-type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=data, method=method, headers=headers
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            raw = response.read()
        if not raw:
            return None
        return json.loads(raw.decode("utf-8"))


@dataclass(frozen=True)
class BuilderStreamEvent:
    event: str
    data: Any


def parse_builder_stream(raw: bytes) -> list[BuilderStreamEvent]:
    events: list[BuilderStreamEvent] = []
    text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n")
    for block in text.split("\n\n"):
        event_name: str | None = None
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].strip())
        if not event_name:
            continue
        raw_data = "\n".join(data_lines)
        parsed_data: Any = None
        if raw_data:
            try:
                parsed_data = json.loads(raw_data)
            except json.JSONDecodeError:
                parsed_data = raw_data
        events.append(BuilderStreamEvent(event=event_name, data=parsed_data))
    return events


def write_stream_artifacts(
    case_dir: Path, name: str, stream: bytes
) -> list[BuilderStreamEvent]:
    (case_dir / f"{name}.sse").write_bytes(stream)
    events = parse_builder_stream(stream)
    write_json(case_dir / f"{name}-events.json", [asdict(event) for event in events])
    return events


def stream_event_names(events: list[BuilderStreamEvent]) -> list[str]:
    return [event.event for event in events]


def stream_requirements_version(events: list[BuilderStreamEvent]) -> str | None:
    for event in events:
        event_data: object = event.data
        if event.event != "requirements_summary" or not isinstance(event_data, dict):
            continue
        data = cast(JsonObject, event_data)
        version = data.get("requirements_version")
        if isinstance(version, str) and version:
            return version
    return None


def stream_error_messages(events: list[BuilderStreamEvent]) -> list[str]:
    errors: list[str] = []
    for event in events:
        event_data: object = event.data
        if event.event != "error":
            continue
        if isinstance(event_data, dict):
            data = cast(JsonObject, event_data)
            message = data.get("message") or data.get("error")
            code = data.get("code") or data.get("intric_error_code")
            if isinstance(message, str) and message:
                if isinstance(code, str) and code:
                    errors.append(f"{code}: {message}")
                else:
                    errors.append(message)
            else:
                errors.append(json.dumps(data, ensure_ascii=False, sort_keys=True))
        elif event_data is not None:
            errors.append(str(event_data))
        else:
            errors.append("Builder returned an unspecified stream error.")
    return errors


def stream_has_question(events: list[BuilderStreamEvent]) -> bool:
    return any(event.event == "question" for event in events)


def main() -> int:
    args = parse_args()
    cases = selected_cases(args)
    if args.list_cases:
        print_case_inventory(CREATE_CASES + SUPPLEMENTAL_CASES)
        return 0

    if not args.api_key:
        print("Missing ENEO_LOCAL_API_KEY or --api-key.", file=sys.stderr)
        return 2

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    spaces = load_spaces(args.state_file)

    client = ApiClient(args.api_base, args.api_key, timeout=args.timeout)
    summary: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "api_base": args.api_base,
        "spaces": spaces,
        "runs": args.runs,
        "applied": args.apply,
        "published": args.publish,
        "score_axes": SCORE_AXES,
        "invocation": redacted_invocation(args),
        "scoring": {
            "score_source": "manual",
            "metrics_source": "manual_plan_or_flow_review",
            "runner_metrics_implementation": "deferred_to_avoid_false_precision",
        },
        "results": [],
    }

    if args.smoke:
        run_smoke(client, output_dir, summary, spaces)

    for run_no in range(1, args.runs + 1):
        for index, case in enumerate(cases):
            space_id = spaces[index % len(spaces)]
            result = run_case(
                client=client,
                case=case,
                run_no=run_no,
                space_id=space_id,
                output_dir=output_dir,
                apply_plan=args.apply,
                publish=args.publish,
                edit_flow_id=args.edit_flow_id,
            )
            summary["results"].append(asdict(result))
            summary["aggregate"] = aggregate_results(summary["results"])
            write_json(output_dir / "summary.json", summary)
            print(
                f"{case.case_id} run {run_no}: {result.status}"
                + (f" flow={result.flow_id}" if result.flow_id else "")
            )

    summary["aggregate"] = aggregate_results(summary["results"])
    write_json(output_dir / "summary.json", summary)
    if args.baseline_label:
        baseline_dir = (
            DEFAULT_OUTPUT_ROOT / "baselines" / sanitize_label(args.baseline_label)
        )
        baseline_dir.mkdir(parents=True, exist_ok=True)
        write_json(baseline_dir / "summary.json", redacted_baseline_summary(summary))
    print(f"Summary written to {output_dir / 'summary.json'}")
    return 0


def selected_cases(args: argparse.Namespace) -> list[EvalCase]:
    all_cases = CREATE_CASES + (SUPPLEMENTAL_CASES if args.include_supplemental else [])
    if args.case_ids:
        wanted = {case_id.upper() for case_id in args.case_ids}
        selected = [case for case in all_cases if case.case_id in wanted]
        missing = sorted(wanted - {case.case_id for case in selected})
        if missing:
            raise SystemExit(f"Unknown case id(s): {', '.join(missing)}")
        return selected
    if args.all:
        return all_cases
    if args.smoke:
        return []
    return CREATE_CASES


def run_smoke(
    client: ApiClient, output_dir: Path, summary: dict[str, Any], spaces: list[str]
) -> None:
    smoke_dir = output_dir / "smoke"
    smoke_dir.mkdir(parents=True, exist_ok=True)
    sessions = client.get_json("/api/v1/flows/ai-builder/sessions")
    write_json(smoke_dir / "sessions.json", sessions)
    flow_lists = {}
    for space_id in spaces:
        query = urllib.parse.urlencode({"space_id": space_id, "limit": 50, "offset": 0})
        data = client.get_json(f"/api/v1/flows/?{query}")
        write_json(smoke_dir / f"flows-{space_id}.json", data)
        flow_lists[space_id] = summarize_list_payload(data)
    summary["smoke"] = {
        "sessions": summarize_list_payload(sessions),
        "flows": flow_lists,
    }


def run_case(
    *,
    client: ApiClient,
    case: EvalCase,
    run_no: int,
    space_id: str,
    output_dir: Path,
    apply_plan: bool,
    publish: bool,
    edit_flow_id: str | None,
) -> CaseRunResult:
    case_dir = output_dir / f"{case.case_id}-run{run_no}"
    case_dir.mkdir(parents=True, exist_ok=True)
    write_json(case_dir / "case.json", asdict(case))
    result = CaseRunResult(
        case_id=case.case_id,
        run_no=run_no,
        suite=case.suite,
        space_id=space_id,
        status="started",
        output_dir=str(case_dir),
    )
    try:
        session_payload: dict[str, Any] = {
            "target_kind": "create",
            "space_id": space_id,
            "force_new": True,
        }
        if case.suite == "edit":
            if not edit_flow_id:
                result.status = "skipped"
                result.error = "edit case requires --edit-flow-id"
                return result
            session_payload = {
                "target_kind": "edit",
                "space_id": space_id,
                "flow_id": edit_flow_id,
                "force_new": True,
            }

        session = client.post_json("/api/v1/flows/ai-builder/sessions", session_payload)
        write_json(case_dir / "session.json", session)
        result.session_id = extract_first(session, "session_id", "id")
        if not result.session_id:
            raise RuntimeError("session response did not include session_id")

        stream = client.post_stream(
            f"/api/v1/flows/ai-builder/sessions/{result.session_id}/messages",
            {"message": case.prompt, "ui_language": "sv"},
        )
        events = write_stream_artifacts(case_dir, "message", stream)
        all_events = list(events)
        result.checkpoints.extend(stream_event_names(events))
        result.builder_errors.extend(stream_error_messages(events))
        result.requirements_version = stream_requirements_version(events)

        session_after = client.get_json(
            f"/api/v1/flows/ai-builder/sessions/{result.session_id}"
        )
        write_json(case_dir / "session-after-message.json", session_after)

        plans = client.get_json(
            f"/api/v1/flows/ai-builder/sessions/{result.session_id}/plans"
        )
        write_json(case_dir / "plans.json", plans)
        result.plan_id = extract_plan_id(plans)

        if not result.plan_id and result.requirements_version:
            confirm_stream = client.post_stream(
                f"/api/v1/flows/ai-builder/sessions/{result.session_id}/messages",
                {
                    "message": "Kraven stämmer. Skapa planen.",
                    "ui_language": "sv",
                    "question_answer": {
                        "requirements_confirmed": True,
                        "requirements_version": result.requirements_version,
                    },
                },
            )
            confirm_events = write_stream_artifacts(
                case_dir, "requirements-confirmation", confirm_stream
            )
            all_events.extend(confirm_events)
            result.checkpoints.extend(stream_event_names(confirm_events))
            result.builder_errors.extend(stream_error_messages(confirm_events))

            session_after_confirm = client.get_json(
                f"/api/v1/flows/ai-builder/sessions/{result.session_id}"
            )
            write_json(
                case_dir / "session-after-requirements-confirmation.json",
                session_after_confirm,
            )

            plans = client.get_json(
                f"/api/v1/flows/ai-builder/sessions/{result.session_id}/plans"
            )
            write_json(case_dir / "plans-after-requirements-confirmation.json", plans)
            result.plan_id = extract_plan_id(plans)

        if result.builder_errors and not result.plan_id:
            result.status = "builder_error"
            result.error = "; ".join(result.builder_errors)
            return result
        if not result.plan_id and stream_has_question(all_events):
            result.status = "clarification_required"
            return result
        if not result.plan_id:
            if result.requirements_version:
                result.status = "no_plan_after_requirements_confirmation"
            else:
                result.status = "no_plan"
            return result

        plan = client.get_json(f"/api/v1/flows/ai-builder/plans/{result.plan_id}")
        write_json(case_dir / "plan.json", plan)

        if not apply_plan:
            result.status = "planned"
            return result

        approved = client.post_json(
            f"/api/v1/flows/ai-builder/plans/{result.plan_id}/approve"
        )
        write_json(case_dir / "approve.json", approved)
        applied = client.post_json(
            f"/api/v1/flows/ai-builder/plans/{result.plan_id}/apply", {}
        )
        write_json(case_dir / "apply.json", applied)
        result.flow_id = extract_first(applied, "flow_id", "id")
        if not result.flow_id and isinstance(applied, dict):
            applied_object = cast(JsonObject, applied)
            result.flow_id = extract_first(applied_object.get("flow"), "flow_id", "id")
        if not result.flow_id:
            result.status = "applied_without_flow_id"
            return result

        inspect_flow_authoring(client, result.flow_id, case_dir)
        if publish:
            published = client.post_json(f"/api/v1/flows/{result.flow_id}/publish/")
            write_json(case_dir / "publish.json", published)
            inspect_published_runtime(client, result.flow_id, case_dir)
        result.status = "applied"
        return result
    except urllib.error.HTTPError as error:
        result.status = "http_error"
        result.error = format_http_error(error)
        (case_dir / "error.txt").write_text(result.error, encoding="utf-8")
        return result
    except urllib.error.URLError as error:
        result.status = "connection_error"
        result.error = (
            f"{error}. Is the backend listening at the configured --api-base?"
        )
        (case_dir / "error.txt").write_text(result.error, encoding="utf-8")
        return result
    except Exception as error:  # noqa: BLE001 - outer eval runner boundary
        result.status = "error"
        result.error = str(error)
        (case_dir / "error.txt").write_text(result.error, encoding="utf-8")
        return result


def inspect_flow_authoring(client: ApiClient, flow_id: str, case_dir: Path) -> None:
    endpoints = {
        "flow.json": f"/api/v1/flows/{flow_id}/",
        "graph.json": f"/api/v1/flows/{flow_id}/graph/",
        "input-policy.json": f"/api/v1/flows/{flow_id}/input-policy/",
        "template-files.json": f"/api/v1/flows/{flow_id}/template-files/",
    }
    inspect_endpoints(client, case_dir, endpoints)


def inspect_published_runtime(client: ApiClient, flow_id: str, case_dir: Path) -> None:
    endpoints = {
        "published.json": f"/api/v1/flows/{flow_id}/published/",
        "run-contract.json": f"/api/v1/flows/{flow_id}/run-contract/",
        "input-policy.json": f"/api/v1/flows/{flow_id}/input-policy/",
    }
    inspect_endpoints(client, case_dir, endpoints)


def inspect_endpoints(
    client: ApiClient, case_dir: Path, endpoints: dict[str, str]
) -> None:
    for filename, path in endpoints.items():
        try:
            write_json(case_dir / filename, client.get_json(path))
        except urllib.error.HTTPError as error:
            (case_dir / f"{filename}.error.txt").write_text(
                format_http_error(error), encoding="utf-8"
            )


def extract_plan_id(payload: Any) -> str | None:
    if isinstance(payload, dict):
        payload_object = cast(JsonObject, payload)
        direct = extract_first(payload_object, "plan_id", "id", "latest_plan_id")
        if direct:
            return direct
        for key in ("plans", "items", "data"):
            child = payload_object.get(key)
            if isinstance(child, list) and child:
                child_list = cast(JsonList, child)
                return extract_first(child_list[0], "plan_id", "id")
    if isinstance(payload, list) and payload:
        payload_list = cast(JsonList, payload)
        return extract_first(payload_list[0], "plan_id", "id")
    return None


def extract_first(payload: Any, *keys: str) -> str | None:
    if not isinstance(payload, dict):
        return None
    payload_object = cast(JsonObject, payload)
    for key in keys:
        value = payload_object.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def summarize_list_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        payload_object = cast(JsonObject, payload)
        for key in ("sessions", "items", "flows", "data"):
            value = payload_object.get(key)
            if isinstance(value, list):
                value_list = cast(JsonList, value)
                return {"count": len(value_list)}
    if isinstance(payload, list):
        payload_list = cast(JsonList, payload)
        return {"count": len(payload_list)}
    return {"count": None}


def format_http_error(error: urllib.error.HTTPError) -> str:
    body = error.read().decode("utf-8", errors="replace")
    return f"HTTP {error.code} {error.reason}\n{body}"


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def redacted_invocation(args: argparse.Namespace) -> dict[str, Any]:
    # Intentionally omit api_key; raw eval outputs are not secret stores.
    return {
        "api_base": args.api_base,
        "output_dir": str(args.output_dir),
        "state_file": str(args.state_file),
        "baseline_label": args.baseline_label,
        "smoke": args.smoke,
        "list_cases": args.list_cases,
        "case_ids": args.case_ids,
        "all": args.all,
        "include_supplemental": args.include_supplemental,
        "runs": args.runs,
        "apply": args.apply,
        "publish": args.publish,
        "edit_flow_id": args.edit_flow_id,
        "timeout": args.timeout,
    }


def default_output_dir() -> Path:
    env_output_dir = os.getenv("ENEO_LIVE_EVAL_DIR")
    if env_output_dir:
        return Path(env_output_dir)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return DEFAULT_OUTPUT_ROOT / timestamp


def load_spaces(state_path: Path) -> list[str]:
    if not state_path.exists():
        raise SystemExit(f"State file not found: {state_path}")
    lines = state_path.read_text(encoding="utf-8").splitlines()
    spaces: list[str] = []
    in_live_eval = False
    in_spaces = False
    spaces_indent: int | None = None
    for line in lines:
        stripped = line.strip()
        if stripped == "live_eval:":
            in_live_eval = True
            in_spaces = False
            continue
        if not in_live_eval:
            continue
        if stripped == "spaces:":
            in_spaces = True
            spaces_indent = len(line) - len(line.lstrip())
            continue
        if in_spaces:
            indent = len(line) - len(line.lstrip())
            if stripped.startswith("- "):
                spaces.append(stripped[2:].strip().strip('"').strip("'"))
                continue
            if stripped and spaces_indent is not None and indent <= spaces_indent:
                break
    if not spaces:
        raise SystemExit(f"No checks.live_eval.spaces entries found in {state_path}")
    return spaces


def aggregate_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_case: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        by_case.setdefault(str(result["case_id"]), []).append(result)

    cases: dict[str, Any] = {}
    for case_id, case_results in by_case.items():
        statuses = [str(result["status"]) for result in case_results]
        axes: dict[str, Any] = {}
        for axis in SCORE_AXES:
            values = [
                result.get("score_axes", {}).get(axis)
                for result in case_results
                if isinstance(result.get("score_axes", {}).get(axis), int)
            ]
            if values:
                axes[axis] = {
                    "median": statistics.median(values),
                    "min": min(values),
                    "max": max(values),
                    "flaky": max(values) - min(values) >= 2,
                }
            else:
                axes[axis] = {
                    "median": None,
                    "min": None,
                    "max": None,
                    "flaky": None,
                    "needs_manual_score": True,
                }
        cases[case_id] = {"runs": len(case_results), "statuses": statuses, "axes": axes}
    return {"cases": cases}


def redacted_baseline_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "generated_at": summary["generated_at"],
        "api_base": summary["api_base"],
        "spaces": summary["spaces"],
        "runs": summary["runs"],
        "applied": summary["applied"],
        "published": summary["published"],
        "invocation": summary.get("invocation"),
        "score_axes": summary["score_axes"],
        "scoring": summary["scoring"],
        "aggregate": summary.get("aggregate", {}),
        "results": [
            {
                "case_id": result["case_id"],
                "run_no": result["run_no"],
                "suite": result["suite"],
                "space_id": result["space_id"],
                "status": result["status"],
                "review_required": result["review_required"],
                "score_axes": result["score_axes"],
                "metrics": result["metrics"],
                "metrics_implementation": result["metrics_implementation"],
                "error": result.get("error"),
            }
            for result in summary["results"]
        ],
    }


def sanitize_label(label: str) -> str:
    sanitized = "".join(
        char if char.isalnum() or char in "-_." else "-" for char in label
    )
    return sanitized.strip(".-") or "baseline"


def print_case_inventory(cases: list[EvalCase]) -> None:
    for case in cases:
        print(f"{case.case_id}\t{case.suite}\t{', '.join(case.tags)}")
        print(f"  {case.prompt}")
        if case.notes:
            print(f"  note: {case.notes}")


if __name__ == "__main__":
    raise SystemExit(main())
