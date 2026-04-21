"""P0.8 — AI Builder baseline benchmark harness.

The committed ``baseline.json`` is **frozen at Phase 0**. These per-PR tests
validate the shape of the harness — schema, determinism, archetype coverage,
archetype-intent invariants — but do NOT assert equality against the frozen
baseline. Phase A-G landings will move metrics; drift is surfaced by the
``--diff`` mode of ``runner.py`` (nightly / on-demand), not by this test.

Regenerating ``baseline.json`` is an explicit phase-boundary decision and is
not performed as part of normal development; the runner's ``--write-baseline``
switch is intentionally verbose.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from tests.integration.flows.ai_builder.benchmark.cases import (
    BENCHMARK_CASES,
    BenchmarkCase,
)
from tests.integration.flows.ai_builder.benchmark.runner import (
    BASELINE_PATH,
    BASELINE_SCHEMA_VERSION,
    PATTERN_SIGNAL_KEYS,
    PHASE_F_METRIC_KEYS,
    _compute_cases_sha256,
    build_current_document,
    compute_case_metrics,
)

EXPECTED_ARCHETYPES = frozenset(
    {
        "vague",
        "rich",
        "attachment_heavy",
        "text_only",
        "audio",
        "document_comparison",
        "template_fill",
        "form_centric",
        "mixed_runtime_input",
        "json_pipeline",
    }
)

QUESTIONING_FLAGS = frozenset({"over_budget", "under_signal", "within_budget"})


class TestBenchmarkCases:
    def test_case_count_in_range(self) -> None:
        assert 15 <= len(BENCHMARK_CASES) <= 20

    def test_case_ids_are_unique(self) -> None:
        ids = [case.case_id for case in BENCHMARK_CASES]
        assert len(ids) == len(set(ids))

    def test_all_archetypes_covered(self) -> None:
        covered = {case.archetype for case in BENCHMARK_CASES}
        assert covered == EXPECTED_ARCHETYPES

    def test_every_archetype_has_at_least_one_case(self) -> None:
        counts = Counter(case.archetype for case in BENCHMARK_CASES)
        for archetype in EXPECTED_ARCHETYPES:
            assert counts[archetype] >= 1


class TestArchetypeIntent:
    """Cheap invariants that keep each prompt honest to its archetype.

    A future edit that swaps a prompt without updating its archetype tag
    should fail here before it reaches the baseline diff.
    """

    @staticmethod
    def _lower(case: BenchmarkCase) -> str:
        return case.prompt.casefold()

    @pytest.mark.parametrize("case", BENCHMARK_CASES, ids=lambda c: c.case_id)
    def test_intent(self, case: BenchmarkCase) -> None:
        text = self._lower(case)
        if case.archetype == "vague":
            assert len(case.prompt.split()) <= 10, (
                f"{case.case_id}: vague archetype requires ≤ 10 words"
            )
        elif case.archetype == "attachment_heavy":
            numeric_counts = any(
                w in text
                for w in (
                    "tre ",
                    "fyra ",
                    "three ",
                    "four ",
                    "flera ",
                    "multiple ",
                    "3 ",
                    "4 ",
                )
            )
            doc_like = any(w in text for w in ("pdf", "dokument", "document", "filer"))
            assert numeric_counts and doc_like, (
                f"{case.case_id}: attachment_heavy must mention ≥ 3 docs"
            )
        elif case.archetype == "audio":
            assert any(
                w in text
                for w in ("transkribera", "transcribe", "ljud", "audio", "interview")
            ), f"{case.case_id}: audio must mention transcription"
        elif case.archetype == "document_comparison":
            assert any(w in text for w in ("jämför", "compare", "skiljer")), (
                f"{case.case_id}: document_comparison must mention comparing"
            )
        elif case.archetype == "template_fill":
            has_template = any(w in text for w in ("mall", "template", "placeholder"))
            has_docx = "docx" in text
            assert has_template and has_docx, (
                f"{case.case_id}: template_fill must mention template + DOCX"
            )
        elif case.archetype == "form_centric":
            assert any(
                w in text
                for w in (
                    "formulärfält",
                    "formulär",
                    "sektioner",
                    "sectioned",
                    "form fields",
                    "intake",
                )
            ), f"{case.case_id}: form_centric must mention form/sections"
        elif case.archetype == "mixed_runtime_input":
            has_form = any(w in text for w in ("formulär", "form", "fält", "field"))
            has_upload = any(
                w in text for w in ("ladd", "upload", "underlag", "attachment", "pdf")
            )
            assert has_form and has_upload, (
                f"{case.case_id}: mixed_runtime_input needs form + attachment"
            )
        elif case.archetype == "json_pipeline":
            assert "json" in text, f"{case.case_id}: json_pipeline must reference JSON"
        elif case.archetype == "text_only":
            assert any(
                w in text
                for w in (
                    "ingen filuppladdning",
                    "no file upload",
                    "text in and text out",
                )
            ), f"{case.case_id}: text_only must assert no upload"
        elif case.archetype == "rich":
            assert len(case.prompt.split()) >= 15, (
                f"{case.case_id}: rich must be an explicit, detailed spec"
            )
        else:
            pytest.fail(f"unhandled archetype {case.archetype!r}")


class TestComputeCaseMetrics:
    @pytest.mark.parametrize("case", BENCHMARK_CASES, ids=lambda c: c.case_id)
    def test_metrics_shape(self, case: BenchmarkCase) -> None:
        metrics = compute_case_metrics(case)
        assert metrics["case_id"] == case.case_id
        assert metrics["archetype"] == case.archetype
        assert metrics["ui_language"] == case.ui_language
        assert metrics["question_budget"] in (1, 3)
        assert metrics["question_count"] >= 0
        assert metrics["questioning_flag"] in QUESTIONING_FLAGS
        assert isinstance(metrics["has_explicit_step_plan"], bool)
        assert set(metrics["pattern_signals"].keys()) == set(PATTERN_SIGNAL_KEYS)
        for key in PATTERN_SIGNAL_KEYS:
            assert isinstance(metrics["pattern_signals"][key], bool)
        assert metrics["blocking_issue_count"] >= 0
        assert isinstance(metrics["selected_question_ids"], list)
        assert metrics["question_count"] == len(metrics["selected_question_ids"])
        assert isinstance(metrics["mvs_met"], bool)
        assert isinstance(metrics["ready_for_confirmation"], bool)
        for key in PHASE_F_METRIC_KEYS:
            assert metrics[key] is None, f"{key} must be null until Phase F"

    @pytest.mark.parametrize("case", BENCHMARK_CASES, ids=lambda c: c.case_id)
    def test_metrics_are_deterministic(self, case: BenchmarkCase) -> None:
        first = compute_case_metrics(case)
        second = compute_case_metrics(case)
        assert first == second


class TestBaselineDocument:
    def test_baseline_file_exists(self) -> None:
        assert BASELINE_PATH.exists(), (
            f"Baseline missing at {BASELINE_PATH}. Freeze with: "
            "uv run python -m tests.integration.flows.ai_builder.benchmark"
            ".runner --write-baseline"
        )

    def test_schema_version_matches(self) -> None:
        committed = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        assert committed["schema_version"] == BASELINE_SCHEMA_VERSION

    def test_one_entry_per_case(self) -> None:
        committed = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        committed_ids = {entry["case_id"] for entry in committed["cases"]}
        case_ids = {case.case_id for case in BENCHMARK_CASES}
        assert committed_ids == case_ids

    def test_sorted_by_case_id(self) -> None:
        committed = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        ids = [entry["case_id"] for entry in committed["cases"]]
        assert ids == sorted(ids), "baseline.json must be sorted by case_id"

    def test_cases_sha256_matches_content(self) -> None:
        committed = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        assert committed["cases_sha256"] == _compute_cases_sha256(committed["cases"]), (
            "baseline.json cases_sha256 does not match its cases content"
        )

    def test_phase_f_fields_null_in_baseline(self) -> None:
        committed = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        for entry in committed["cases"]:
            for key in PHASE_F_METRIC_KEYS:
                assert entry[key] is None, (
                    f"baseline case {entry['case_id']} has non-null {key}; "
                    "Phase F metrics should arrive via Phase F commits, not "
                    "backfilled into the Phase 0 baseline"
                )

    def test_current_document_produces_valid_sha(self) -> None:
        current = build_current_document()
        assert current["cases_sha256"] == _compute_cases_sha256(current["cases"])


def test_baseline_path_under_benchmark_dir() -> None:
    assert BASELINE_PATH.name == "baseline.json"
    assert BASELINE_PATH.parent == Path(__file__).parent
