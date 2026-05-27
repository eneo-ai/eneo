// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  IntricError,
  type FlowRunReviewCheckpoint,
  type FlowRun,
  type Intric
} from "@intric/intric-js";
import { m } from "$lib/paraglide/messages";

import FlowRunReviewCheckpointPanel from "./FlowRunReviewCheckpointPanel.svelte";

vi.mock("$lib/components/toast", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn()
  }
}));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => {});
});

function buildCheckpoint(
  state: FlowRunReviewCheckpoint["state"],
  revision: number
): FlowRunReviewCheckpoint {
  return {
    id: "checkpoint-1",
    tenant_id: "tenant-1",
    flow_id: "flow-1",
    flow_run_id: "run-1",
    step_id: "step-1",
    step_order: 2,
    attempt_no: 1,
    state,
    revision,
    schema_version: 1,
    original_payload_json: { text: "Draft answer." },
    current_payload_json: { text: "Reviewed answer." },
    step_label: "Review answer",
    review_mode: "edit",
    output_type: "json",
    output_contract: { type: "object", properties: { text: { type: "string" } } },
    next_step_ids: ["step-2"],
    requester_user_id: "user-1",
    requester_principal_type: "user",
    decided_by_user_id: null,
    decided_by_principal_type: null,
    edited_at: null,
    approved_at: state === "approved" || state === "resumed" ? "2026-03-17T10:07:00Z" : null,
    rejected_at: null,
    resumed_at: state === "resumed" ? "2026-03-17T10:08:00Z" : null,
    cancelled_at: null,
    expires_at: "2099-03-17T10:35:00Z",
    expired_at: state === "expired" ? "2026-03-17T10:35:00Z" : null,
    created_at: "2026-03-17T10:05:00Z",
    updated_at: "2026-03-17T10:05:00Z"
  };
}

function buildRun(status: FlowRun["status"]): FlowRun {
  return {
    id: "run-1",
    flow_id: "flow-1",
    flow_version: 1,
    tenant_id: "tenant-1",
    trace_id: "trace-1",
    revision: 2,
    status,
    result_files: [],
    created_at: "2026-03-17T10:05:00Z",
    updated_at: "2026-03-17T10:05:00Z"
  };
}

function buildEneo({
  activeCheckpoint,
  active,
  edit = vi.fn(),
  approve = vi.fn(),
  reject = vi.fn(),
  resume = vi.fn()
}: {
  activeCheckpoint: FlowRunReviewCheckpoint | null;
  active?: ReturnType<typeof vi.fn>;
  edit?: ReturnType<typeof vi.fn>;
  approve?: ReturnType<typeof vi.fn>;
  reject?: ReturnType<typeof vi.fn>;
  resume?: ReturnType<typeof vi.fn>;
}) {
  return {
    flows: {
      runs: {
        reviewCheckpoints: {
          active: active ?? vi.fn(async () => activeCheckpoint),
          edit,
          approve,
          reject,
          resume
        }
      }
    }
  };
}

describe("FlowRunReviewCheckpointPanel", () => {
  it("shows the empty state when the run has no active review checkpoint", async () => {
    const eneo = buildEneo({ activeCheckpoint: null });

    render(FlowRunReviewCheckpointPanel, {
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Intric }
    });

    await screen.findByText(m.flow_run_review_no_active_checkpoint());
  });

  it("can retry a failed checkpoint load", async () => {
    const active = vi
      .fn()
      .mockRejectedValueOnce(new Error("Load failed"))
      .mockResolvedValueOnce(buildCheckpoint("awaiting_review", 1));
    const eneo = buildEneo({ activeCheckpoint: null, active });

    render(FlowRunReviewCheckpointPanel, {
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Intric }
    });

    await screen.findByText(m.flow_run_review_load_failed());
    await fireEvent.click(screen.getByRole("button", { name: m.flow_retry() }));

    await screen.findByText(m.flow_run_review_state_awaiting_review());
    expect(active).toHaveBeenCalledTimes(2);
  });

  it("shows stale edit errors from the checkpoint revision contract", async () => {
    const staleError = new IntricError(
      "Review checkpoint revision is stale.",
      "RESPONSE",
      400,
      9007,
      { code: "flow_review_stale_revision" },
      { endpoint: "PATCH@/review-checkpoints/checkpoint-1" }
    );
    const edit = vi.fn(async () => {
      throw staleError;
    });
    const eneo = buildEneo({ activeCheckpoint: buildCheckpoint("awaiting_review", 1), edit });

    render(FlowRunReviewCheckpointPanel, {
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Intric }
    });

    const payloadEditor = await screen.findByLabelText(m.flow_run_review_current_payload());
    await fireEvent.input(payloadEditor, {
      target: { value: JSON.stringify({ text: "Edited answer." }, null, 2) }
    });
    await fireEvent.click(screen.getByRole("button", { name: m.flow_run_review_save_edit() }));

    await screen.findByText(m.flow_error_flow_review_stale_revision());
    expect(edit).toHaveBeenCalledWith({
      flowId: "flow-1",
      runId: "run-1",
      checkpointId: "checkpoint-1",
      expectedCheckpointRevision: 1,
      currentPayloadJson: { text: "Edited answer." }
    });
  });

  it("shows expired review errors from the shared Flow API error contract", async () => {
    const expiredError = new IntricError(
      "Review checkpoint has expired.",
      "RESPONSE",
      400,
      9007,
      {
        code: "flow_review_expired",
        context: {
          checkpoint_id: "checkpoint-1",
          state: "awaiting_review",
          expires_at: "2026-03-17T10:35:00Z"
        }
      },
      { endpoint: "POST@/review-checkpoints/checkpoint-1/approve" }
    );
    const approve = vi.fn(async () => {
      throw expiredError;
    });
    const eneo = buildEneo({ activeCheckpoint: buildCheckpoint("awaiting_review", 1), approve });

    render(FlowRunReviewCheckpointPanel, {
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Intric }
    });

    await screen.findByText(m.flow_run_review_state_awaiting_review());
    await fireEvent.click(screen.getByRole("button", { name: m.approve() }));

    await screen.findByText(m.flow_error_flow_review_expired());
  });

  it("shows typed contract edit errors from the shared Flow API error contract", async () => {
    const contractError = new IntricError(
      "backend readable fallback",
      "RESPONSE",
      400,
      9007,
      {
        code: "typed_io_contract_violation",
        context: {
          checkpoint_id: "checkpoint-1",
          step_id: "step-1",
          step_order: 1,
          payload_field: "structured"
        }
      },
      { endpoint: "PATCH@/review-checkpoints/checkpoint-1" }
    );
    const edit = vi.fn(async () => {
      throw contractError;
    });
    const eneo = buildEneo({ activeCheckpoint: buildCheckpoint("awaiting_review", 1), edit });

    render(FlowRunReviewCheckpointPanel, {
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Intric }
    });

    const payloadEditor = await screen.findByLabelText(m.flow_run_review_current_payload());
    await fireEvent.input(payloadEditor, {
      target: { value: JSON.stringify({ text: "Edited answer." }, null, 2) }
    });
    await fireEvent.click(screen.getByRole("button", { name: m.flow_run_review_save_edit() }));

    await screen.findByText(m.flow_error_typed_io_contract_violation());
    expect(screen.queryByText("backend readable fallback")).toBeNull();
  });

  it("keeps invalid and non-object payloads out of edit requests", async () => {
    const edit = vi.fn();
    const eneo = buildEneo({ activeCheckpoint: buildCheckpoint("awaiting_review", 1), edit });

    render(FlowRunReviewCheckpointPanel, {
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Intric }
    });

    const payloadEditor = await screen.findByLabelText(m.flow_run_review_current_payload());
    await fireEvent.input(payloadEditor, {
      target: { value: "{bad" }
    });
    await fireEvent.click(screen.getByRole("button", { name: m.flow_run_review_save_edit() }));

    await screen.findByText(m.flow_run_review_payload_invalid());
    expect(edit).not.toHaveBeenCalled();

    await fireEvent.input(payloadEditor, {
      target: { value: "[]" }
    });
    await fireEvent.click(screen.getByRole("button", { name: m.flow_run_review_save_edit() }));

    expect(edit).not.toHaveBeenCalled();
  });

  it("approves and resumes through checkpoint state returned by the backend", async () => {
    const approvedCheckpoint = buildCheckpoint("approved", 2);
    const resumedCheckpoint = buildCheckpoint("resumed", 3);
    const approve = vi.fn(async () => approvedCheckpoint);
    const resume = vi.fn(async () => ({
      checkpoint: resumedCheckpoint,
      run: buildRun("queued")
    }));
    const onChanged = vi.fn();
    const eneo = buildEneo({
      activeCheckpoint: buildCheckpoint("awaiting_review", 1),
      approve,
      resume
    });

    render(FlowRunReviewCheckpointPanel, {
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Intric, onChanged }
    });

    await screen.findByText(m.flow_run_review_state_awaiting_review());
    await fireEvent.click(screen.getByRole("button", { name: m.approve() }));
    await screen.findByText(m.flow_run_review_state_approved());
    await fireEvent.click(screen.getByRole("button", { name: m.flow_run_review_resume() }));

    await waitFor(() => expect(resume).toHaveBeenCalledTimes(1));
    expect(approve).toHaveBeenCalledWith({
      flowId: "flow-1",
      runId: "run-1",
      checkpointId: "checkpoint-1",
      expectedCheckpointRevision: 1
    });
    expect(resume).toHaveBeenCalledWith({
      flowId: "flow-1",
      runId: "run-1",
      checkpointId: "checkpoint-1",
      expectedCheckpointRevision: 2,
      idempotencyKey: "flow-review-resume:checkpoint-1:2"
    });
    expect(onChanged).toHaveBeenCalledTimes(2);
  });

  it("shows the review deadline and blocks decision actions after it passes", async () => {
    const expiredCheckpoint = {
      ...buildCheckpoint("awaiting_review", 1),
      expires_at: "2000-01-01T10:00:00Z"
    };
    const edit = vi.fn();
    const approve = vi.fn();
    const reject = vi.fn();
    const eneo = buildEneo({ activeCheckpoint: expiredCheckpoint, edit, approve, reject });

    render(FlowRunReviewCheckpointPanel, {
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Intric }
    });

    await screen.findByText(m.flow_run_review_deadline_expired());

    expect(
      (screen.getByRole("button", { name: m.flow_run_review_save_edit() }) as HTMLButtonElement)
        .disabled
    ).toBe(true);
    expect((screen.getByRole("button", { name: m.approve() }) as HTMLButtonElement).disabled).toBe(
      true
    );
    expect((screen.getByRole("button", { name: m.reject() }) as HTMLButtonElement).disabled).toBe(
      true
    );

    expect(edit).not.toHaveBeenCalled();
    expect(approve).not.toHaveBeenCalled();
    expect(reject).not.toHaveBeenCalled();
  });

  it("shows backend-expired checkpoints as expired and non-editable", async () => {
    const eneo = buildEneo({ activeCheckpoint: buildCheckpoint("expired", 2) });

    render(FlowRunReviewCheckpointPanel, {
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Intric }
    });

    await screen.findByText(m.flow_run_review_state_expired());
    await screen.findByText(m.flow_run_review_deadline_expired());

    expect(
      (screen.getByRole("button", { name: m.flow_run_review_save_edit() }) as HTMLButtonElement)
        .disabled
    ).toBe(true);
    expect((screen.getByRole("button", { name: m.approve() }) as HTMLButtonElement).disabled).toBe(
      true
    );
    expect((screen.getByRole("button", { name: m.reject() }) as HTMLButtonElement).disabled).toBe(
      true
    );
  });

  it("does not show deadline help when the checkpoint has no deadline", async () => {
    const checkpointWithoutDeadline = {
      ...buildCheckpoint("awaiting_review", 1),
      expires_at: null
    };
    const eneo = buildEneo({ activeCheckpoint: checkpointWithoutDeadline });

    render(FlowRunReviewCheckpointPanel, {
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Intric }
    });

    await screen.findByText(m.flow_run_review_state_awaiting_review());

    expect(screen.queryByText(m.flow_run_review_deadline_help())).toBeNull();
  });

  it("allows resume after an approved checkpoint even when the original deadline has passed", async () => {
    const approvedCheckpoint = {
      ...buildCheckpoint("approved", 2),
      expires_at: "2000-01-01T10:00:00Z"
    };
    const resumedCheckpoint = buildCheckpoint("resumed", 3);
    const resume = vi.fn(async () => ({
      checkpoint: resumedCheckpoint,
      run: buildRun("queued")
    }));
    const eneo = buildEneo({ activeCheckpoint: approvedCheckpoint, resume });

    render(FlowRunReviewCheckpointPanel, {
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Intric }
    });

    await screen.findByText(m.flow_run_review_deadline_approved());
    await fireEvent.click(screen.getByRole("button", { name: m.flow_run_review_resume() }));

    await waitFor(() => expect(resume).toHaveBeenCalledTimes(1));
  });

  it("requires and trims the reviewer reject reason", async () => {
    const reject = vi.fn(async () => buildCheckpoint("rejected", 2));
    const eneo = buildEneo({ activeCheckpoint: buildCheckpoint("awaiting_review", 1), reject });

    render(FlowRunReviewCheckpointPanel, {
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Intric }
    });

    await screen.findByText(m.flow_run_review_state_awaiting_review());
    expect((screen.getByRole("button", { name: m.reject() }) as HTMLButtonElement).disabled).toBe(
      true
    );

    await fireEvent.input(screen.getByLabelText(m.flow_run_review_reject_reason()), {
      target: { value: "   " }
    });

    expect((screen.getByRole("button", { name: m.reject() }) as HTMLButtonElement).disabled).toBe(
      true
    );
    expect(reject).not.toHaveBeenCalled();

    await fireEvent.input(screen.getByLabelText(m.flow_run_review_reject_reason()), {
      target: { value: "  Needs changes.  " }
    });

    await waitFor(() =>
      expect((screen.getByRole("button", { name: m.reject() }) as HTMLButtonElement).disabled).toBe(
        false
      )
    );
    await fireEvent.click(screen.getByRole("button", { name: m.reject() }));

    await waitFor(() => expect(reject).toHaveBeenCalledTimes(1));
    expect(reject).toHaveBeenCalledWith({
      flowId: "flow-1",
      runId: "run-1",
      checkpointId: "checkpoint-1",
      expectedCheckpointRevision: 1,
      reason: "Needs changes."
    });
  });

  it("disables review actions when the backend checkpoint state is already final", async () => {
    const eneo = buildEneo({ activeCheckpoint: buildCheckpoint("resumed", 3) });

    render(FlowRunReviewCheckpointPanel, {
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Intric }
    });

    await screen.findByText(m.flow_run_review_state_resumed());

    expect(
      (screen.getByRole("button", { name: m.flow_run_review_save_edit() }) as HTMLButtonElement)
        .disabled
    ).toBe(true);
    expect((screen.getByRole("button", { name: m.approve() }) as HTMLButtonElement).disabled).toBe(
      true
    );
    expect((screen.getByRole("button", { name: m.reject() }) as HTMLButtonElement).disabled).toBe(
      true
    );
    expect(
      (screen.getByRole("button", { name: m.flow_run_review_resume() }) as HTMLButtonElement)
        .disabled
    ).toBe(true);
  });
});
