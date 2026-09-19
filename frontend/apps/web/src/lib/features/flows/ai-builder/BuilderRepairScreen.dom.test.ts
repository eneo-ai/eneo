import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import type { AIBuilderError, AIBuilderRunFailureLaunch } from "./protocol";
import BuilderRepairScreen from "./BuilderRepairScreen.svelte";

const TARGET = { runId: "run-1", stepOrder: 2 };

function makeLaunch(overrides: Partial<AIBuilderRunFailureLaunch> = {}): AIBuilderRunFailureLaunch {
  return {
    reference: {
      kind: "run_failure",
      flow_version: 4,
      definition_checksum: "sum-4",
      run_id: "run-1",
      step_order: 2
    },
    evidence_classification_level: 1,
    step_number: 2,
    step_name: "Sammanfatta",
    attempt_no: 3,
    error_code: "typed_io_output_parse_failed",
    ...overrides
  };
}

function refusal(code: string, reason?: string): AIBuilderError {
  return {
    schema_version: 2,
    code,
    category: "bad_request",
    message: "server text",
    phase: "client",
    request_id: null,
    diagnostic_context: null,
    details: reason ? { reason } : {}
  };
}

afterEach(() => {
  cleanup();
});

describe("BuilderRepairScreen", () => {
  it("names the failed step and sends the server's reference when a fix is asked for", async () => {
    const onprepare = vi.fn();
    render(BuilderRepairScreen, {
      repair: { status: "ready", launch: makeLaunch() },
      onprepare,
      onclose: vi.fn(),
      onretry: vi.fn()
    });
    const text = screen.getByTestId("builder-repair").textContent ?? "";
    expect(text).toContain(
      m.ai_builder_repair_lead({ step: "2", name: "Sammanfatta", version: "4" })
    );
    expect(text).toContain(m.flow_error_typed_io_output_parse_failed());
    expect(text).toContain("3");

    await fireEvent.click(screen.getByTestId("repair-prepare"));
    expect(onprepare).toHaveBeenCalledWith({
      message: m.ai_builder_repair_message({ step: "2" }),
      reviewContext: makeLaunch().reference
    });
  });

  it("says what is read for a truncated answer, which was never kept", () => {
    render(BuilderRepairScreen, {
      repair: { status: "ready", launch: makeLaunch({ error_code: "flow_llm_output_truncated" }) },
      onprepare: vi.fn(),
      onclose: vi.fn(),
      onretry: vi.fn()
    });
    const text = screen.getByTestId("builder-repair").textContent ?? "";
    expect(text).toContain(m.flow_error_flow_llm_output_truncated());
    expect(text).toContain(m.ai_builder_repair_hint_truncated());
    expect(text).not.toContain(m.ai_builder_repair_hint());
    expect(screen.getByTestId("repair-prepare")).toBeTruthy();
  });

  it("explains each refusal in words and retries only an unexplained failure", () => {
    const cases: Array<[AIBuilderError, string, boolean]> = [
      [refusal("review_stale"), m.ai_builder_repair_stale_body(), false],
      [
        refusal("review_finding_unknown", "no_failed_attempt"),
        m.ai_builder_repair_succeeded_later_body(),
        false
      ],
      [
        refusal("review_finding_unknown", "output_not_retained"),
        m.ai_builder_repair_output_not_retained_body(),
        false
      ],
      [
        refusal("review_finding_unknown", "step_unknown"),
        m.ai_builder_repair_step_unknown_body(),
        false
      ],
      [refusal("flow_not_published"), m.ai_builder_review_unpublished_body(), false],
      [refusal("unknown"), "server text", true]
    ];
    for (const [error, body, retry] of cases) {
      const onretry = vi.fn();
      const view = render(BuilderRepairScreen, {
        repair: { status: "failed", target: TARGET, error },
        onprepare: vi.fn(),
        onclose: vi.fn(),
        onretry
      });
      expect(screen.getByTestId("repair-unavailable").textContent).toContain(body);
      const retryButton = screen.queryByRole("button", { name: m.ai_builder_review_retry() });
      expect(retryButton !== null).toBe(retry);
      if (retryButton) {
        void fireEvent.click(retryButton);
        expect(onretry).toHaveBeenCalledWith(TARGET);
      }
      view.unmount();
    }
  });
});
