from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = BACKEND_ROOT / "scripts" / "check_flow_run_evidence_acceptance.py"
sys.path.append(str(SCRIPT.parent))
import check_flow_run_evidence_acceptance as acceptance  # noqa: E402


def test_evidence_acceptance_script_accepts_per_source_run(tmp_path: Path) -> None:
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(_evidence()), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(evidence_path),
            "--expected-source-count",
            "2",
            "--require-extraction-warning-file",
            "FULLTEXT01.pdf",
        ],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS per_source_call_count" in result.stdout
    assert "PASS compose_zero_tokens" in result.stdout
    assert "PASS extraction_warning:FULLTEXT01.pdf" in result.stdout


def test_evidence_acceptance_checks_rendered_pdf_text() -> None:
    checks = acceptance.check_evidence(
        _evidence(),
        expected_source_count=2,
        max_per_source_input_tokens=100_000,
        required_extraction_warning_files=set(),
        rendered_pdf_text="Rapport\nKälla: FULLTEXT01.pdf\nKälla: Socialpsykologi.pdf",
    )

    assert _passed(checks, "source_lines_in_pdf")
    assert _passed(checks, "source_labels_in_pdf")


def test_evidence_acceptance_rejects_rendered_pdf_without_source_labels() -> None:
    checks = acceptance.check_evidence(
        _evidence(),
        expected_source_count=2,
        max_per_source_input_tokens=100_000,
        required_extraction_warning_files=set(),
        rendered_pdf_text="Rapport utan källrader",
    )

    assert not _passed(checks, "source_lines_in_pdf")


def test_evidence_acceptance_rejects_source_labels_as_headings() -> None:
    checks = acceptance.check_evidence(
        _evidence(
            final_text=(
                "# Rapport\n\n"
                "## FULLTEXT01.pdf\n\n"
                "Källa: FULLTEXT01.pdf\n\n"
                "## Socialpsykologi.pdf\n\n"
                "Källa: Socialpsykologi.pdf\n"
            )
        ),
        expected_source_count=2,
        max_per_source_input_tokens=100_000,
        required_extraction_warning_files=set(),
    )

    assert not _passed(checks, "source_labels_not_headings")


def test_evidence_acceptance_rejects_all_previous_step() -> None:
    checks = acceptance.check_evidence(
        _evidence(compose_input_source="all_previous_steps"),
        expected_source_count=2,
        max_per_source_input_tokens=100_000,
        required_extraction_warning_files=set(),
    )

    assert not _passed(checks, "no_all_previous_steps")


def test_evidence_acceptance_script_rejects_placeholder_source_labels(
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(
        json.dumps(_evidence(first_label="uploaded_source_1")),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(evidence_path),
            "--expected-source-count",
            "2",
        ],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 1
    assert "FAIL no_placeholder_source_labels" in result.stdout


def _passed(checks: list[dict[str, object]], name: str) -> bool:
    return any(check["name"] == name and check["passed"] is True for check in checks)


def _evidence(
    *,
    first_label: str = "FULLTEXT01.pdf",
    compose_input_source: str = "previous_step",
    final_text: str | None = None,
) -> dict[str, object]:
    report_text = final_text or (
        "# Rapport\n\n"
        "## Fulltext-källan\n\n"
        "Källa: FULLTEXT01.pdf\n\n"
        "## Socialpsykologi\n\n"
        "Källa: Socialpsykologi.pdf\n"
    )
    return {
        "bundle": {
            "step_results": [
                {
                    "step_order": 1,
                    "input_source": "flow_input",
                    "input_payload_json": {
                        "runtime_input": {
                            "execution_mode": "per_source",
                            "files": [
                                {
                                    "id": "file-1",
                                    "name": "FULLTEXT01.pdf",
                                    "extraction_warnings": [
                                        "pdf_text_likely_reversed",
                                    ],
                                },
                                {"id": "file-2", "name": "Socialpsykologi.pdf"},
                            ],
                            "per_source_calls": [
                                {
                                    "source_label": first_label,
                                    "num_tokens_input": 1200,
                                },
                                {
                                    "source_label": "Socialpsykologi.pdf",
                                    "num_tokens_input": 800,
                                },
                            ],
                        }
                    },
                    "model_parameters_json": {
                        "runtime_input_execution_mode": "per_source",
                        "per_source_call_count": 2,
                    },
                    "output_payload_json": {
                        "structured": {
                            "documents": [
                                {
                                    "source_label": first_label,
                                    "source_file_id": "file-1",
                                },
                                {
                                    "source_label": "Socialpsykologi.pdf",
                                    "source_file_id": "file-2",
                                },
                            ]
                        }
                    },
                },
                {
                    "step_order": 2,
                    "input_source": compose_input_source,
                    "num_tokens_input": 0,
                    "num_tokens_output": 0,
                    "model_parameters_json": {"mode": "compose_text"},
                    "output_payload_json": {
                        "text": report_text,
                        "structured": {
                            "source_sections": [
                                {
                                    "section_title": "Fulltext-källan",
                                    "section_body": "Avsnitt.",
                                    "source_label": first_label,
                                    "source_file_id": "file-1",
                                },
                                {
                                    "section_title": "Socialpsykologi",
                                    "section_body": "Avsnitt.",
                                    "source_label": "Socialpsykologi.pdf",
                                    "source_file_id": "file-2",
                                },
                            ]
                        },
                    },
                },
                {
                    "step_order": 3,
                    "input_source": "previous_step",
                    "num_tokens_input": 0,
                    "num_tokens_output": 0,
                    "model_parameters_json": {"mode": "render_verbatim"},
                    "output_payload_json": {"text": report_text},
                },
            ]
        }
    }
