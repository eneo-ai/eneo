"""History reads never mutate; any mutation needs a live flow.

A retired (deleted) flow is admitted only where a call passes `history=` with a
value other than False. This test fixes every such call site, so a new caller,
a mutating route above all, cannot admit retired flows without being listed
here and reviewed.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "src" / "eneo"

# The read routes that opt into history mode, with `history=True` literals.
READ_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("flows/api/flow_run_lifecycle_router.py", "list_flow_runs"),
        ("flows/api/flow_run_lifecycle_router.py", "get_flow_run_status"),
        ("flows/api/flow_run_lifecycle_router.py", "get_flow_run"),
        ("flows/api/flow_run_steps_router.py", "list_flow_run_steps"),
        ("flows/api/flow_run_steps_router.py", "get_flow_graph"),
        ("flows/api/flow_run_steps_router.py", "generate_flow_run_artifact_signed_url"),
        (
            "flows/api/flow_run_steps_router.py",
            "generate_flow_run_input_file_signed_url",
        ),
        ("flows/api/flow_run_evidence_router.py", "get_flow_run_evidence"),
        ("flows/api/flow_run_evidence_router.py", "list_flow_run_provider_calls"),
        ("flows/api/flow_run_evidence_router.py", "export_flow_run_evidence"),
        (
            "flows/api/flow_run_review_router.py",
            "list_flow_run_review_checkpoint_edits",
        ),
        (
            "flows/api/flow_run_review_router.py",
            "get_active_flow_run_review_checkpoint",
        ),
        (
            "flows/api/flow_run_transcript_corrections_router.py",
            "list_flow_run_transcript_correction_revisions",
        ),
        (
            "flows/api/flow_run_transcript_corrections_router.py",
            "list_flow_run_transcript_corrections",
        ),
        (
            "flows/api/flow_run_transcript_words_router.py",
            "get_flow_run_transcript_words",
        ),
        (
            "flows/api/flow_transcript_source_router.py",
            "get_flow_run_transcript_source",
        ),
    }
)
# POST only because a signed URL is minted; they read, never change, the run.
SIGNED_URL_READS = frozenset(
    {"generate_flow_run_artifact_signed_url", "generate_flow_run_input_file_signed_url"}
)

# Service and policy methods that pass their own `history` parameter on.
FORWARDERS: frozenset[tuple[str, str]] = frozenset(
    {
        ("flows/application/flow_run_access_policy.py", name)
        for name in (
            "FlowRunAccessPolicy._ensure_sensitive_flow_export_allowed",
            "FlowRunAccessPolicy.can_list_all_runs_in_flow",
            "FlowRunAccessPolicy.ensure_can_access_run",
            "FlowRunAccessPolicy.load_run",
            "FlowRunAccessPolicy.load_run_status",
            "FlowRunAccessPolicy.load_space_access",
            "FlowRunAccessPolicy.passage_disclosure_for_run",
            "FlowRunAccessPolicy.space_role",
        )
    }
    | {
        (
            "flows/application/flow_run_evidence_service.py",
            f"FlowRunEvidenceService.{name}",
        )
        for name in (
            "_get_evidence_bundle",
            "_get_redacted_evidence_bundle",
            "export_evidence_json",
            "get_redacted_evidence_bundle",
            "get_run",
            "get_run_artifact_file",
            "get_run_input_file",
            "list_provider_calls",
            "list_review_checkpoint_edits",
            "list_transcript_correction_revisions",
        )
    }
    | {
        ("flows/application/flow_run_service.py", f"FlowRunService.{name}")
        for name in (
            "_lists_every_run",
            "get_run",
            "get_run_detail_with_result_files_and_usage",
            "get_run_status",
            "get_run_versioned_view",
            "get_run_with_result_files_and_usage",
            "list_run_statuses",
            "list_step_results_with_files",
        )
    }
    | {
        (
            "flows/application/flow_run_review_checkpoint_service.py",
            "FlowRunReviewCheckpointService.get_active_review_checkpoint",
        ),
        (
            "flows/application/flow_transcript_corrections_service.py",
            "FlowTranscriptCorrectionsService.list_for_run",
        ),
        (
            "flows/application/flow_transcript_words_service.py",
            "FlowTranscriptWordsService.get_for_step",
        ),
    }
    | {
        (
            "flows/application/flow_transcript_source_service.py",
            f"FlowTranscriptSourceService.{name}",
        )
        for name in (
            "_load_attempt",
            "get_for_attempt",
            "get_reference_for_attempt",
            "get_references_for_step_results",
        )
    }
)


def _history_sites() -> tuple[
    dict[tuple[str, str], set[str]], dict[tuple[str, str], ast.AST]
]:
    sites: dict[tuple[str, str], set[str]] = {}
    functions: dict[tuple[str, str], ast.AST] = {}
    for path in sorted(SRC.rglob("*.py")):
        relative = str(path.relative_to(SRC))
        tree = ast.parse(path.read_text(encoding="utf-8"))
        stack: list[str] = []

        def visit(node: ast.AST) -> None:
            scoped = isinstance(
                node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
            )
            if scoped:
                stack.append(node.name)  # type: ignore[attr-defined]
                functions[(relative, ".".join(stack))] = node
            if isinstance(node, ast.Call):
                for keyword in node.keywords:
                    value = keyword.value
                    if keyword.arg == "history" and not (
                        isinstance(value, ast.Constant) and value.value is False
                    ):
                        sites.setdefault((relative, ".".join(stack)), set()).add(
                            ast.unparse(value)
                        )
            for child in ast.iter_child_nodes(node):
                visit(child)
            if scoped:
                stack.pop()

        visit(tree)
    return sites, functions


def test_only_listed_read_routes_and_forwarders_admit_a_retired_flow() -> None:
    sites, _functions = _history_sites()

    assert set(sites) == READ_ROUTES | FORWARDERS
    for site in READ_ROUTES:
        assert sites[site] == {"True"}, site
    for site in FORWARDERS:
        assert sites[site] == {"history"}, site


def test_history_read_routes_are_reads() -> None:
    _sites, functions = _history_sites()

    for site in READ_ROUTES:
        route = functions[site]
        assert isinstance(route, ast.AsyncFunctionDef), site
        methods = {
            decorator.func.attr
            for decorator in route.decorator_list
            if isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and isinstance(decorator.func.value, ast.Name)
            and decorator.func.value.id == "router"
        }
        expected = {"post"} if site[1] in SIGNED_URL_READS else {"get"}
        assert methods == expected, site


def test_every_history_parameter_is_keyword_only_and_defaults_to_live() -> None:
    _sites, functions = _history_sites()

    declared = 0
    for site, node in functions.items():
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        arguments = node.args
        assert "history" not in {
            argument.arg for argument in arguments.posonlyargs + arguments.args
        }, site
        for argument, default in zip(
            arguments.kwonlyargs, arguments.kw_defaults, strict=True
        ):
            if argument.arg != "history":
                continue
            declared += 1
            # Private forwarders may require it; public entry points default live.
            if default is None:
                assert site[1].rsplit(".", 1)[-1].startswith("_"), site
            else:
                assert isinstance(default, ast.Constant), site
                assert default.value is False, site
    assert declared >= len(FORWARDERS)
