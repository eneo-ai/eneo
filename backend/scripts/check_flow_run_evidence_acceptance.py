#!/usr/bin/env python3
"""Check a downloaded Flow evidence bundle for per-source reader acceptance."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import cast

PLACEHOLDER_LABELS = ("uploaded_source_", "[SOURCE", "okänt", "unknown", "unspecified")
Json = dict[str, object]


def main() -> int:
    args = _parse_args()
    raw_evidence = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
    if not isinstance(raw_evidence, dict):
        raise ValueError("Evidence file must contain a JSON object.")
    evidence = cast(Json, raw_evidence)
    checks = check_evidence(
        evidence,
        expected_source_count=args.expected_source_count,
        max_per_source_input_tokens=args.max_per_source_input_tokens,
        required_extraction_warning_files=set(args.require_extraction_warning_file),
    )
    failed = [check for check in checks if not check["passed"]]
    for check in checks:
        status = "PASS" if check["passed"] else "FAIL"
        print(f"{status} {check['name']}: {check['actual']}")
    return 1 if failed else 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate Flow run evidence for per-source document-reader acceptance."
    )
    parser.add_argument("evidence", help="Downloaded flow-run-evidence-*.json file.")
    parser.add_argument("--expected-source-count", type=int, default=None)
    parser.add_argument("--max-per-source-input-tokens", type=int, default=100_000)
    parser.add_argument(
        "--require-extraction-warning-file",
        action="append",
        default=[],
        help="Filename that must carry an extraction warning. Repeat as needed.",
    )
    return parser.parse_args()


def check_evidence(
    evidence: Json,
    *,
    expected_source_count: int | None,
    max_per_source_input_tokens: int,
    required_extraction_warning_files: set[str],
) -> list[Json]:
    bundle = evidence.get("bundle")
    if not isinstance(bundle, dict):
        bundle = evidence
    bundle = cast(Json, bundle)
    step_results = _dict_list(bundle.get("step_results"))
    reader = _find_reader_step(step_results)
    render = step_results[-1] if step_results else {}
    reader_input = _dict(reader.get("input_payload_json"))
    runtime_input = _dict(reader_input.get("runtime_input"))
    model_params = _dict(reader.get("model_parameters_json"))
    calls = _dict_list(runtime_input.get("per_source_calls"))
    files = _dict_list(runtime_input.get("files"))
    documents = _documents(reader)
    final_text = _string(_dict(render.get("output_payload_json")).get("text"))
    render_params = _dict(render.get("model_parameters_json"))
    render_input_tokens = _int(render.get("num_tokens_input"))
    render_output_tokens = _int(render.get("num_tokens_output"))

    checks: list[Json] = []
    add = checks.append
    source_count = len(calls)
    expected_count = expected_source_count if expected_source_count is not None else source_count
    max_tokens = max((_int(call.get("num_tokens_input")) or 0 for call in calls), default=0)
    labels = [_string(call.get("source_label")) for call in calls]
    file_names = [_string(file.get("name")) for file in files]
    document_labels = [_string(document.get("source_label")) for document in documents]

    add(
        _check(
            "runtime_execution_mode",
            runtime_input.get("execution_mode") == "per_source",
            runtime_input.get("execution_mode"),
        )
    )
    add(
        _check(
            "model_execution_mode",
            model_params.get("runtime_input_execution_mode") == "per_source",
            model_params.get("runtime_input_execution_mode"),
        )
    )
    add(_check("per_source_call_count", source_count == expected_count, source_count))
    add(
        _check(
            "model_per_source_call_count",
            model_params.get("per_source_call_count") == expected_count,
            model_params.get("per_source_call_count"),
        )
    )
    add(_check("files_count", len(files) == expected_count, len(files)))
    add(_check("documents_count", len(documents) == expected_count, len(documents)))
    add(_check("max_per_source_input_tokens", max_tokens < max_per_source_input_tokens, max_tokens))
    add(_check("no_placeholder_source_labels", not _has_placeholder(labels + document_labels), labels + document_labels))
    add(_check("source_labels_match_files", _labels_match_files(document_labels, file_names), {"labels": document_labels, "files": file_names}))
    add(_check("source_file_ids_match_files", _document_ids_match_files(documents, files), [document.get("source_file_id") for document in documents]))
    add(
        _check(
            "render_verbatim_mode",
            render_params.get("mode") == "render_verbatim",
            render_params.get("mode"),
        )
    )
    add(
        _check(
            "render_zero_tokens",
            render_input_tokens == 0 and render_output_tokens == 0,
            {"in": render_input_tokens, "out": render_output_tokens},
        )
    )
    add(_check("source_lines_in_final_text", final_text.count("Källa:") >= expected_count, final_text.count("Källa:")))
    add(_check("source_labels_in_final_text", all(f"Källa: {label}" in final_text for label in document_labels), document_labels))
    for filename in sorted(required_extraction_warning_files):
        add(_check(f"extraction_warning:{filename}", _has_extraction_warning(runtime_input, filename), filename))
    return checks


def _find_reader_step(step_results: list[Json]) -> Json:
    for step in step_results:
        model_params = _dict(step.get("model_parameters_json"))
        runtime_input = _dict(_dict(step.get("input_payload_json")).get("runtime_input"))
        if (
            model_params.get("runtime_input_execution_mode") == "per_source"
            or runtime_input.get("execution_mode") == "per_source"
        ):
            return step
    return {}


def _documents(reader: Json) -> list[Json]:
    output = _dict(reader.get("output_payload_json"))
    structured = _dict(output.get("structured"))
    return _dict_list(structured.get("documents"))


def _has_placeholder(labels: list[str]) -> bool:
    for label in labels:
        folded = label.casefold()
        if any(marker.casefold() in folded for marker in PLACEHOLDER_LABELS):
            return True
    return False


def _labels_match_files(labels: list[str], file_names: list[str]) -> bool:
    if len(labels) != len(file_names):
        return False
    return all(label == file_name or label.startswith(f"{file_name} (") for label, file_name in zip(labels, file_names, strict=True))


def _document_ids_match_files(documents: list[Json], files: list[Json]) -> bool:
    if len(documents) != len(files):
        return False
    return all(_string(document.get("source_file_id")) == _string(file.get("id")) for document, file in zip(documents, files, strict=True))


def _has_extraction_warning(runtime_input: Json, filename: str) -> bool:
    for source in _dict_list(runtime_input.get("files")) + _dict_list(
        runtime_input.get("source_headers")
    ):
        name = _string(source.get("name") or source.get("file_name"))
        if name == filename and _list(source.get("extraction_warnings")):
            return True
    for call in _dict_list(runtime_input.get("per_source_calls")):
        if _string(call.get("source_label")) != filename:
            continue
        if _list(call.get("extraction_warnings")):
            return True
        for diagnostic in _dict_list(call.get("diagnostics")):
            if _string(diagnostic.get("severity")) == "warning":
                return True
    return False


def _check(name: str, passed: bool, actual: object) -> Json:
    return {"name": name, "passed": passed, "actual": actual}


def _dict(value: object) -> Json:
    return cast(Json, value) if isinstance(value, dict) else {}


def _dict_list(value: object) -> list[Json]:
    if not isinstance(value, list):
        return []
    return [cast(Json, item) for item in cast(list[object], value) if isinstance(item, dict)]


def _list(value: object) -> list[object]:
    return cast(list[object], value) if isinstance(value, list) else []


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _int(value: object) -> int | None:
    return value if isinstance(value, int) else None


if __name__ == "__main__":
    raise SystemExit(main())
