from __future__ import annotations

import ast
import pathlib

import pytest

import intric.flows.ai_builder.ai_builder_discovery as discovery
from intric.flows.ai_builder.ai_builder_discovery_profile_builder import (
    build_discovery_profile,
)
from intric.flows.ai_builder.ai_builder_domain_models import ConversationMessage

_EXPECTED_BUILDER_NAMES: tuple[str, ...] = (
    "_build_comparison_scope_conflict_issue",
    "_build_case_scope_issue",
    "_build_input_material_mode_issue",
    "_build_flow_input_architecture_issue",
    "_build_document_kind_issue",
    "_build_document_material_scope_issue",
    "_build_comparison_scope_issue",
    "_build_external_delivery_unsupported_issue",
    "_build_structured_io_contract_issue",
    "_build_post_processing_goal_issue",
    "_build_final_output_mode_issue",
    "_build_docx_output_mode_issue",
    "_build_pdf_generation_mode_issue",
    "_build_output_reader_issue",
    "_build_final_output_scope_issue",
    "_build_final_pdf_type_issue",
    "_build_structured_analysis_need_issue",
    "_build_runtime_metadata_fields_issue",
)

_EXPECTED_ISSUE_ID_BY_BUILDER: dict[str, str] = {
    "_build_comparison_scope_conflict_issue": "comparison_scope_conflict",
    "_build_case_scope_issue": "case_scope",
    "_build_input_material_mode_issue": "input_material_mode",
    "_build_flow_input_architecture_issue": "flow_input_architecture",
    "_build_document_kind_issue": "document_kind",
    "_build_document_material_scope_issue": "document_material_scope",
    "_build_comparison_scope_issue": "comparison_scope",
    "_build_external_delivery_unsupported_issue": "external_delivery_unsupported",
    "_build_structured_io_contract_issue": "structured_io_contract",
    "_build_post_processing_goal_issue": "post_processing_goal",
    "_build_final_output_mode_issue": "final_output_mode",
    "_build_docx_output_mode_issue": "docx_output_mode",
    "_build_pdf_generation_mode_issue": "pdf_generation_mode",
    "_build_output_reader_issue": "output_reader",
    "_build_final_output_scope_issue": "final_output_scope",
    "_build_final_pdf_type_issue": "final_pdf_type",
    "_build_structured_analysis_need_issue": "structured_analysis_need",
    "_build_runtime_metadata_fields_issue": "runtime_metadata_fields",
}


def _discovery_ast() -> ast.Module:
    module_path = pathlib.Path(discovery.__file__)
    return ast.parse(module_path.read_text(encoding="utf-8"))


def _function_node(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Missing discovery issue builder {name!r}")


def _issue_id_from_keyword(value: ast.expr) -> str:
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    if (
        isinstance(value, ast.Name)
        and value.id == "EXTERNAL_DELIVERY_UNSUPPORTED_ISSUE_ID"
    ):
        return "external_delivery_unsupported"
    raise AssertionError(f"Unsupported issue_id expression: {ast.unparse(value)}")


def _issue_ids_constructed_by(function_node: ast.FunctionDef) -> frozenset[str]:
    issue_ids: set[str] = set()
    for node in ast.walk(function_node):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "DiscoveryIssue":
            continue
        for keyword in node.keywords:
            if keyword.arg == "issue_id":
                issue_ids.add(_issue_id_from_keyword(keyword.value))
    return frozenset(issue_ids)


def test_discovery_issue_builders_pin_current_precedence_order() -> None:
    assert [builder.__name__ for builder in discovery._DISCOVERY_ISSUE_BUILDERS] == [
        *list(_EXPECTED_BUILDER_NAMES)
    ]


def test_discovery_issue_builder_tuple_is_declared_final() -> None:
    tree = _discovery_ast()
    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "_DISCOVERY_ISSUE_BUILDERS"
        ):
            annotation = ast.unparse(node.annotation)
            assert annotation == "Final[tuple[DiscoveryIssueBuilder, ...]]"
            return
    raise AssertionError("_DISCOVERY_ISSUE_BUILDERS must be a typed Final tuple")


def test_discovery_issue_builders_construct_declared_issue_ids() -> None:
    tree = _discovery_ast()
    for builder_name, expected_issue_id in _EXPECTED_ISSUE_ID_BY_BUILDER.items():
        function_node = _function_node(tree, builder_name)
        assert _issue_ids_constructed_by(function_node) == frozenset(
            {expected_issue_id}
        )


def test_final_output_mode_builder_prefers_output_vague_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(discovery, "_looks_like_output_is_vague", lambda profile: True)
    monkeypatch.setattr(
        discovery, "_ultra_vague_output_choice_is_vague", lambda profile: True
    )
    conversation = [
        ConversationMessage(
            role="user",
            content="Summarize uploaded documents.",
            metadata={"ui_language": "en"},
        )
    ]
    profile = build_discovery_profile(conversation)

    issue = discovery._build_final_output_mode_issue(conversation, profile)

    assert issue is not None
    assert issue.issue_id == "final_output_mode"
    assert issue.message == (
        "The final output format is still too vague to design the flow confidently."
    )
