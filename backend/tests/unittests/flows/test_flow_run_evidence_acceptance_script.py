from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = BACKEND_ROOT / "scripts" / "check_flow_run_evidence_acceptance.py"


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
    assert "PASS extraction_warning:FULLTEXT01.pdf" in result.stdout


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


def _evidence(*, first_label: str = "FULLTEXT01.pdf") -> dict[str, object]:
    final_text = (
        "# Rapport\n\n"
        "Källa: FULLTEXT01.pdf\n\n"
        "Källa: Socialpsykologi.pdf\n"
    )
    return {
        "bundle": {
            "step_results": [
                {
                    "step_order": 1,
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
                    "num_tokens_input": 0,
                    "num_tokens_output": 0,
                    "model_parameters_json": {"mode": "render_verbatim"},
                    "output_payload_json": {"text": final_text},
                },
            ]
        }
    }
