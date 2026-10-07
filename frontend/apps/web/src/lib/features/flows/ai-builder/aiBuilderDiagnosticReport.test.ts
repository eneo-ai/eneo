import { describe, expect, it } from "vitest";

import { parseAIBuilderError } from "./aiBuilderError";
import type { AIBuilderErrorDetails } from "./protocol";
import {
  AIBuilderIssueKind,
  buildAIBuilderDiagnosticReport,
  formatAIBuilderDiagnosticReport,
  type AIBuilderDiagnosticReportSession
} from "./aiBuilderDiagnosticReport";

const session: AIBuilderDiagnosticReportSession = {
  session_id: "session-1",
  target_kind: "edit",
  flow_id: "flow-1",
  latest_plan_id: "plan-1",
  telemetry: {
    last_request_id: "request-last",
    last_model: "model-a",
    last_outcome_kind: "planned"
  }
};

describe("aiBuilderDiagnosticReport", () => {
  it.each<{ name: string; code: string; details: AIBuilderErrorDetails }>([
    {
      name: "new template repair fields",
      code: "architecture_materialization_failed",
      details: {
        architecture_error_code: "architecture_materialization_failed",
        architecture_repair_disposition: "user_action",
        failure_code: "template_placeholder_unresolved",
        unresolved_placeholders: "diarienummer, handläggare"
      }
    },
    {
      name: "new critic IDs and count",
      code: "architecture_critic_invariant_failed",
      details: {
        architecture_error_code: "architecture_critic_invariant_failed",
        architecture_repair_disposition: "server_defect",
        critic_issue_ids: "invariant-a,invariant-b",
        critic_issue_count: 2
      }
    },
    {
      name: "previously persisted scalar diagnostics",
      code: "architecture_materialization_failed",
      details: {
        architecture_error_detail: "OLD_PERSISTED_DIAGNOSTIC_SENTINEL",
        failure_code: "template_attachment_selection_invalid",
        step_index: 3
      }
    }
  ])("keeps $name through the error reader and technical copy", ({ code, details }) => {
    // Kill narrowing the legacy reader or dropping current repair/critic copy fields.
    const error = parseAIBuilderError({
      transport: "sse",
      payload: JSON.stringify({
        schema_version: 2,
        code,
        category: "bad_request",
        phase: "proposal",
        message: "The AI planner could not build this flow.",
        eneo_error_code: 9000,
        request_id: "request-error",
        diagnostic_context: {},
        details
      })
    });
    const report = buildAIBuilderDiagnosticReport({
      kind: "error",
      surface: "chat_stream",
      session,
      error
    });
    expect(error.details).toEqual(details);
    expect(report.details).toEqual(details);
    const rendered = formatAIBuilderDiagnosticReport(report);
    for (const [key, value] of Object.entries(details)) {
      expect(rendered).toContain(`- ${key}: ${value}`);
    }
  });

  it("formats public errors with diagnostic_context and details kept separate", () => {
    const report = buildAIBuilderDiagnosticReport({
      generated_at: "2026-05-21T20:00:00.000Z",
      kind: "error",
      surface: "plan_apply",
      session,
      plan: { plan_id: "plan-1", status: "approved" },
      error: {
        code: "flow_is_published",
        category: "conflict",
        phase: "router",
        message: "Flow is published",
        request_id: "request-error",
        eneo_error_code: 40015,
        diagnostic_context: {
          session_id: "session-from-error",
          flow_id: "flow-from-error"
        },
        details: {
          published_version: 4,
          auth_layer: "flow"
        }
      }
    });

    expect(report.diagnostic_context).toEqual({
      session_id: "session-from-error",
      plan_id: "plan-1",
      request_id: "request-error",
      flow_id: "flow-from-error",
      target_kind: "edit",
      model: "model-a",
      outcome_kind: "planned"
    });
    expect(report.details).toEqual({ published_version: 4, auth_layer: "flow" });

    const rendered = formatAIBuilderDiagnosticReport(report);
    expect(rendered).toContain("surface: plan_apply");
    expect(rendered).toContain("- code: flow_is_published");
    expect(rendered).toContain("- published_version: 4");
    expect(rendered).toContain("- auth_layer: flow");
  });

  it("uses issue_kind and an explicit step ref for non-error step reports", () => {
    const report = buildAIBuilderDiagnosticReport({
      generated_at: "2026-05-21T20:01:00.000Z",
      kind: "quality",
      surface: "step_quality",
      issue_kind: AIBuilderIssueKind.WrongOutputType,
      session,
      plan: { plan_id: "plan-1", status: "proposed" },
      step: {
        plan_step_ref: "step_b",
        step_name: "Create report",
        step_number: 2,
        input_type: "text",
        output_type: "json"
      },
      details: {
        expected_output_type: "docx",
        actual_output_type: "json"
      }
    });

    expect(report.error).toBeNull();
    expect(report.issue_kind).toBe(AIBuilderIssueKind.WrongOutputType);
    expect(report.context.plan_step_ref).toBe("step_b");
    expect(report.context.request_id).toBe("request-last");
    expect(report.context.request_id_source).toBe("session_telemetry_last");

    const rendered = formatAIBuilderDiagnosticReport(report);
    expect(rendered).toContain("issue_kind: wrong_output_type");
    expect(rendered).toContain("- plan_step_ref: step_b");
    expect(rendered).toContain("- expected_output_type: docx");
    expect(rendered).toContain("- actual_output_type: json");
  });

  it("formats plan-quality lint warnings without classifying them as bad edits", () => {
    const report = buildAIBuilderDiagnosticReport({
      generated_at: "2026-05-21T20:02:00.000Z",
      kind: "quality",
      surface: "plan_quality",
      issue_kind: AIBuilderIssueKind.QualityWarning,
      session,
      plan: { plan_id: "plan-1", status: "proposed" },
      details: {
        lint_warning_count: 1,
        advisory_count: 0
      }
    });

    expect(report.issue_kind).toBe(AIBuilderIssueKind.QualityWarning);

    const rendered = formatAIBuilderDiagnosticReport(report);
    expect(rendered).toContain("issue_kind: quality_warning");
    expect(rendered).toContain("- lint_warning_count: 1");
    expect(rendered).not.toContain("issue_kind: bad_edit_result");
  });

  it("rejects raw prompt, full conversation, and full plan inputs at compile time", () => {
    function compileTimeOnly() {
      buildAIBuilderDiagnosticReport({
        kind: "quality",
        surface: "plan_quality",
        issue_kind: AIBuilderIssueKind.Other,
        session,
        plan: { plan_id: "plan-1", status: "proposed" },
        // @ts-expect-error prompt text is not an allow-listed report input.
        promptText: "Build a flow from this private request"
      });

      buildAIBuilderDiagnosticReport({
        kind: "quality",
        surface: "plan_quality",
        issue_kind: AIBuilderIssueKind.Other,
        session: {
          session_id: "session-1",
          target_kind: "edit",
          // @ts-expect-error full conversation payloads are not diagnostic-report inputs.
          conversation: [{ role: "user", content: "private request" }]
        },
        plan: { plan_id: "plan-1", status: "proposed" }
      });

      buildAIBuilderDiagnosticReport({
        kind: "quality",
        surface: "plan_quality",
        issue_kind: AIBuilderIssueKind.Other,
        session,
        plan: {
          plan_id: "plan-1",
          status: "proposed",
          // @ts-expect-error full plan JSON is not a diagnostic-report input.
          proposal: { spec: { steps: [] } }
        }
      });
    }

    expect(compileTimeOnly).toBeTypeOf("function");
  });
});
