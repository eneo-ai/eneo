import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  EneoError,
  type FlowRunReviewCheckpoint,
  type FlowRunReviewCheckpointEditPage,
  type FlowRun,
  type Eneo
} from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";

import { makeFlowRun } from "./flowRunHistoryTestFixtures";
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
    original_payload_json: {
      text: '{"answer": "Draft answer."}',
      structured: { answer: "Draft answer." }
    },
    current_payload_json: {
      text: '{"answer": "Reviewed answer."}',
      structured: { answer: "Reviewed answer." }
    },
    step_label: "Review answer",
    review_mode: "edit",
    output_type: "json",
    output_contract: { type: "object", properties: { answer: { type: "string" } } },
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
  // The canonical fixture carries every field the generated contract requires,
  // so a grown contract fails here at compile time instead of at runtime.
  return makeFlowRun({
    revision: 2,
    status,
    result_files: [],
    created_at: "2026-03-17T10:05:00Z",
    updated_at: "2026-03-17T10:05:00Z"
  });
}

const emptyHistory: FlowRunReviewCheckpointEditPage = {
  baseline: { revision: 1, payload_json: null, payload_sha256: "0".repeat(64) },
  items: [],
  next_after_revision: null,
  truncated: false
};

function buildEneo({
  activeCheckpoint,
  steps,
  inputFileSignedUrl,
  active,
  edits,
  edit = vi.fn(),
  approve = vi.fn(),
  approveAndContinue = vi.fn(),
  reject = vi.fn(),
  resume = vi.fn()
}: {
  activeCheckpoint: FlowRunReviewCheckpoint | null;
  active?: ReturnType<typeof vi.fn>;
  edits?: ReturnType<typeof vi.fn>;
  edit?: ReturnType<typeof vi.fn>;
  approve?: ReturnType<typeof vi.fn>;
  approveAndContinue?: ReturnType<typeof vi.fn>;
  reject?: ReturnType<typeof vi.fn>;
  resume?: ReturnType<typeof vi.fn>;
  steps?: ReturnType<typeof vi.fn>;
  inputFileSignedUrl?: ReturnType<typeof vi.fn>;
}) {
  return {
    users: { me: vi.fn(async () => ({ id: "user-1" })) },
    flows: {
      runs: {
        steps: steps ?? vi.fn(async () => []),
        inputFileSignedUrl:
          inputFileSignedUrl ??
          vi.fn(async () => ({ url: "https://app.test/f", expires_at: 4102444800 })),
        transcriptCorrections: {
          list: vi.fn(async () => []),
          save: vi.fn(async (args) => ({
            revision: 1,
            stale: false,
            occurrences: args.occurrences,
            speaker_edits: args.speakerEdits
          }))
        },
        transcriptSource: {
          // Serve the fixture's transcript through the paged route: one page,
          // the whole-source hash, speaker review on the first page.
          get: vi.fn(async ({ stepId }: { stepId: string }) => {
            const list = (await (steps ?? (async () => []))()) as Array<{
              step_id: string;
              input_payload_json?: { transcription?: Record<string, unknown> };
            }>;
            const t = list.find((step) => step.step_id === stepId)?.input_payload_json
              ?.transcription;
            const segments = Array.isArray(t?.segments) ? t.segments : null;
            if (!segments) return { status: "unavailable_pre_row" };
            return {
              status: "present",
              run_id: "run-1",
              step_id: stepId,
              attempt_no: 1,
              source_hash: typeof t?.segments_hash === "string" ? t.segments_hash : "a".repeat(64),
              start_segment_index: 0,
              page_size: 200,
              max_response_bytes: 16 * 1024 * 1024,
              next_segment_index: null,
              speaker_review: t?.speaker_review ?? null,
              segments: segments.map((segment, index) => ({ segment_index: index, ...segment })),
              bounds: {},
              component_omissions: { detail: null, words: null }
            };
          })
        },
        transcriptWords: { get: vi.fn(async () => null) },
        reviewCheckpoints: {
          active: active ?? vi.fn(async () => activeCheckpoint),
          edits: edits ?? vi.fn(async () => emptyHistory),
          edit,
          approve,
          approveAndContinue,
          reject,
          resume
        }
      }
    }
  };
}

describe("FlowRunReviewCheckpointPanel", () => {
  it("names the step and keeps unsaved changes distinct from saved differences", async () => {
    const checkpoint = buildCheckpoint("awaiting_review", 1);
    const edit = vi.fn(async () => ({
      ...checkpoint,
      revision: 2,
      state: "edited" as const,
      current_payload_json: { structured: { answer: "New answer" } }
    }));
    const eneo = buildEneo({ activeCheckpoint: checkpoint, edit });
    render(FlowRunReviewCheckpointPanel, {
      flowId: "flow-1",
      runId: "run-1",
      eneo: eneo as unknown as Eneo
    });
    await screen.findByRole("heading", { name: "Review answer" });
    expect(screen.queryByText(m.flow_run_review_unsaved())).toBeNull();
    expect(
      screen.getByRole("button", { name: m.flow_run_review_save_edit() }).hasAttribute("disabled")
    ).toBe(true);
    await fireEvent.input(screen.getByLabelText("Answer"), { target: { value: "New answer" } });
    expect(screen.getByText(m.flow_run_review_unsaved())).toBeTruthy();
    await fireEvent.click(screen.getByRole("button", { name: m.flow_run_review_save_edit() }));
    await waitFor(() => expect(screen.queryByText(m.flow_run_review_unsaved())).toBeNull());
    expect(screen.getByText(m.flow_run_review_changed())).toBeTruthy();
    expect((screen.getByLabelText("Answer") as HTMLTextAreaElement).value).toBe("New answer");
  });

  it("edits a schema-labelled field and saves it before approving the visible result", async () => {
    const checkpoint = buildCheckpoint("awaiting_review", 1);
    checkpoint.output_contract = {
      type: "object",
      properties: {
        answer: { type: "string", title: "Brukarens önskemål" }
      }
    };
    checkpoint.current_payload_json = {
      structured: { answer: "Nuvarande önskemål", retained: { ref: "F001" } }
    };
    const saved = {
      ...checkpoint,
      state: "edited" as const,
      revision: 2,
      current_payload_json: { structured: { answer: "Rättat önskemål", retained: { ref: "F001" } } }
    };
    const edit = vi.fn(async () => saved);
    const approveAndContinue = vi.fn(async () => ({
      checkpoint: { ...saved, state: "resumed" as const, revision: 4 },
      run: buildRun("queued")
    }));
    const eneo = buildEneo({ activeCheckpoint: checkpoint, edit, approveAndContinue });
    render(FlowRunReviewCheckpointPanel, {
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Eneo }
    });
    const field = await screen.findByLabelText("Brukarens önskemål");
    await fireEvent.input(field, { target: { value: "Rättat önskemål" } });
    await fireEvent.click(
      screen.getByRole("button", { name: m.flow_transcript_editor_approve_continue() })
    );
    await waitFor(() => expect(approveAndContinue).toHaveBeenCalledTimes(1));
    expect(edit).toHaveBeenCalledWith(
      expect.objectContaining({
        expectedCheckpointRevision: 1,
        editedValue: { answer: "Rättat önskemål", retained: { ref: "F001" } }
      })
    );
    // The key follows the saved revision: the edit is part of the decision.
    expect(approveAndContinue).toHaveBeenCalledWith(
      expect.objectContaining({
        expectedCheckpointRevision: 2,
        idempotencyKey: "flow-review-continue:checkpoint-1:2"
      })
    );
    expect(edit.mock.invocationCallOrder[0]).toBeLessThan(
      approveAndContinue.mock.invocationCallOrder[0]
    );
  });

  it("keeps the visible edit and does not approve when saving it fails", async () => {
    const edit = vi.fn(async () => {
      throw new Error("Save unavailable");
    });
    const approveAndContinue = vi.fn();
    const eneo = buildEneo({
      activeCheckpoint: buildCheckpoint("awaiting_review", 1),
      edit,
      approveAndContinue
    });
    render(FlowRunReviewCheckpointPanel, {
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Eneo }
    });
    const field = await screen.findByLabelText("Answer");
    await fireEvent.input(field, { target: { value: "Keep my correction" } });
    await fireEvent.click(
      screen.getByRole("button", { name: m.flow_transcript_editor_approve_continue() })
    );
    await waitFor(() => expect(edit).toHaveBeenCalledTimes(1));
    // The failed save surfaces before any continuation is attempted: an
    // unsaved correction must never reach the run.
    await screen.findByText(m.flow_run_review_approve_failed());
    expect(approveAndContinue).not.toHaveBeenCalled();
    expect((field as HTMLTextAreaElement).value).toBe("Keep my correction");
  });

  it("shows the original result as read-only fields without replacing the draft", async () => {
    const eneo = buildEneo({ activeCheckpoint: buildCheckpoint("awaiting_review", 1) });
    render(FlowRunReviewCheckpointPanel, {
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Eneo }
    });
    await fireEvent.input(await screen.findByLabelText("Answer"), { target: { value: "Unsaved" } });
    await fireEvent.click(screen.getByRole("button", { name: m.flow_run_review_show_original() }));
    expect(await screen.findByText("Draft answer.")).toBeTruthy();
    expect(screen.queryByLabelText("Answer")).toBeNull();
    expect(
      screen.queryByRole("button", { name: m.flow_transcript_editor_approve_continue() })
    ).toBeNull();
    await fireEvent.click(
      screen.getAllByRole("button", { name: m.flow_run_review_back_to_edit() })[0]
    );
    expect(screen.getByDisplayValue("Unsaved").hasAttribute("disabled")).toBe(false);
    expect(screen.queryByLabelText(m.flow_run_review_json_payload())).toBeNull();
  });

  it("saves pending plain text before approval too", async () => {
    const checkpoint = {
      ...buildCheckpoint("awaiting_review", 1),
      output_type: "text" as const,
      output_contract: null,
      current_payload_json: { text: "Original document" }
    };
    const edit = vi.fn(async () => ({
      ...checkpoint,
      state: "edited" as const,
      revision: 2,
      current_payload_json: { text: "Corrected document" }
    }));
    const approveAndContinue = vi.fn(async () => ({
      checkpoint: { ...checkpoint, state: "resumed" as const, revision: 4 },
      run: buildRun("queued")
    }));
    const eneo = buildEneo({ activeCheckpoint: checkpoint, edit, approveAndContinue });
    render(FlowRunReviewCheckpointPanel, {
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Eneo }
    });
    await fireEvent.input(await screen.findByLabelText(m.flow_run_review_current_payload()), {
      target: { value: "Corrected document" }
    });
    await fireEvent.click(
      screen.getByRole("button", { name: m.flow_transcript_editor_approve_continue() })
    );
    await waitFor(() => expect(approveAndContinue).toHaveBeenCalledTimes(1));
    expect(edit).toHaveBeenCalledWith(
      expect.objectContaining({ editedValue: "Corrected document" })
    );
    expect(approveAndContinue).toHaveBeenCalledWith(
      expect.objectContaining({ expectedCheckpointRevision: 2 })
    );
  });

  it("shows the empty state when the run has no active review checkpoint", async () => {
    const eneo = buildEneo({ activeCheckpoint: null });

    render(FlowRunReviewCheckpointPanel, {
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Eneo }
    });

    await screen.findByText(m.flow_run_review_no_active_checkpoint());
  });

  function buildHistoryPage(checkpoint: FlowRunReviewCheckpoint): FlowRunReviewCheckpointEditPage {
    return {
      baseline: {
        revision: 1,
        payload_json: checkpoint.original_payload_json ?? null,
        payload_sha256: "a".repeat(64)
      },
      items: [
        {
          id: "edit-2",
          tenant_id: "tenant-1",
          flow_id: "flow-1",
          flow_run_id: "run-1",
          checkpoint_id: "checkpoint-1",
          revision: 2,
          cause: "reviewer_edit",
          corrections_revision_id: null,
          payload_json: {
            text: '{"answer": "First pass."}',
            structured: { answer: "First pass." }
          },
          payload_sha256_before: "a".repeat(64),
          payload_sha256_after: "b".repeat(64),
          edited_by_user_id: "user-1",
          edited_by_service_id: null,
          edited_by_principal_type: "user",
          edited_by_service_principal: null,
          created_at: "2026-03-17T10:06:00Z"
        },
        {
          id: "edit-3",
          tenant_id: "tenant-1",
          flow_id: "flow-1",
          flow_run_id: "run-1",
          checkpoint_id: "checkpoint-1",
          revision: 3,
          cause: "corrections_folded",
          corrections_revision_id: "rev-1",
          payload_json: checkpoint.current_payload_json ?? {},
          payload_sha256_before: "b".repeat(64),
          payload_sha256_after: "c".repeat(64),
          edited_by_user_id: null,
          edited_by_service_id: "service-1",
          edited_by_principal_type: "service_key",
          edited_by_service_principal: { id: "service-1", display_name: "Kommunroboten" },
          created_at: "2026-03-17T10:07:00Z"
        }
      ],
      next_after_revision: null,
      truncated: false
    };
  }

  it("lists the checkpoint's saved changes and shows what a selected one changed", async () => {
    const checkpoint = buildCheckpoint("edited", 3);
    const edits = vi.fn(async () => buildHistoryPage(checkpoint));
    const eneo = buildEneo({ activeCheckpoint: checkpoint, edits });

    render(FlowRunReviewCheckpointPanel, {
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Eneo }
    });

    await screen.findByText(m.flow_run_review_history_revision({ revision: 2 }));
    expect(edits).toHaveBeenCalledWith({
      flowId: "flow-1",
      runId: "run-1",
      checkpointId: "checkpoint-1",
      afterRevision: null
    });
    expect(screen.getByText(m.flow_run_review_history_cause_corrections_folded())).toBeTruthy();
    expect(
      screen.getByText(m.flow_run_review_history_editor_service({ name: "Kommunroboten" }))
    ).toBeTruthy();
    // The signed-in reviewer's own change reads as "you".
    await screen.findByText(m.flow_run_review_history_editor_you());

    await fireEvent.click(
      screen.getByRole("button", {
        name: new RegExp(m.flow_run_review_history_revision({ revision: 3 }))
      })
    );

    // Revision 3 is explained against revision 2, not against the original.
    expect(screen.getByText(m.flow_run_review_history_before())).toBeTruthy();
    const panes = screen.getAllByText(/First pass\.|Reviewed answer\./);
    expect(panes.some((node) => node.textContent?.includes("First pass."))).toBe(true);
    expect(panes.some((node) => node.textContent?.includes("Reviewed answer."))).toBe(true);
  });

  it("names another reviewer's change by id, not as the signed-in user", async () => {
    const checkpoint = buildCheckpoint("edited", 3);
    const page = buildHistoryPage(checkpoint);
    page.items[0] = { ...page.items[0], edited_by_user_id: "b2c3d4e5-0000-4000-8000-000000000002" };
    const eneo = buildEneo({ activeCheckpoint: checkpoint, edits: vi.fn(async () => page) });

    render(FlowRunReviewCheckpointPanel, {
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Eneo }
    });

    await screen.findByText(m.flow_run_review_history_editor_user({ id: "b2c3d4e5" }));
    expect(screen.queryByText(m.flow_run_review_history_editor_you())).toBeNull();
  });

  it("keeps the history it has and offers a retry when a page fails", async () => {
    const checkpoint = buildCheckpoint("edited", 3);
    const edits = vi
      .fn()
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce(buildHistoryPage(checkpoint));
    const eneo = buildEneo({ activeCheckpoint: checkpoint, edits });

    render(FlowRunReviewCheckpointPanel, {
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Eneo }
    });

    await screen.findByText(m.flow_run_review_history_load_failed());
    await fireEvent.click(screen.getAllByRole("button", { name: m.retry() }).at(-1) as HTMLElement);
    await screen.findByText(m.flow_run_review_history_revision({ revision: 2 }));
    expect(screen.queryByText(m.flow_run_review_history_load_failed())).toBeNull();
    expect(edits).toHaveBeenCalledTimes(2);
  });

  it("ignores a history response that arrives after a newer request", async () => {
    const checkpoint = buildCheckpoint("edited", 3);
    const fullPage = buildHistoryPage(checkpoint);
    const stalePage = { ...fullPage, items: [fullPage.items[0]] };
    let releaseStale: (page: FlowRunReviewCheckpointEditPage) => void = () => {};
    const edits = vi
      .fn()
      .mockImplementationOnce(
        () => new Promise<FlowRunReviewCheckpointEditPage>((resolve) => (releaseStale = resolve))
      )
      .mockResolvedValueOnce(fullPage);
    const approveAndContinue = vi.fn(async () => ({
      checkpoint: buildCheckpoint("resumed", 5),
      run: buildRun("queued")
    }));
    const eneo = buildEneo({ activeCheckpoint: checkpoint, edits, approveAndContinue });

    render(FlowRunReviewCheckpointPanel, {
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Eneo }
    });

    // The first (stale) request is still pending when approval refreshes the history.
    await screen.findByRole("button", { name: m.flow_transcript_editor_approve_continue() });
    await fireEvent.click(
      screen.getByRole("button", { name: m.flow_transcript_editor_approve_continue() })
    );
    await screen.findByText(m.flow_run_review_history_revision({ revision: 3 }));
    releaseStale(stalePage);
    await waitFor(() => expect(edits).toHaveBeenCalledTimes(2));
    expect(screen.getByText(m.flow_run_review_history_revision({ revision: 3 }))).toBeTruthy();
  });

  it("renders the citation summary attached to the active checkpoint", async () => {
    const checkpoint = {
      ...buildCheckpoint("awaiting_review", 1),
      citation_summary: {
        status: "observed",
        sources: [
          { identity_resolved: true, display_name: "Riktlinjer.pdf", container_label: null }
        ],
        matched_cited_source_count: 1,
        sources_truncated: false,
        stale_after_edit: false
      }
    } as FlowRunReviewCheckpoint;
    const eneo = buildEneo({ activeCheckpoint: checkpoint });

    render(FlowRunReviewCheckpointPanel, {
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Eneo }
    });

    await screen.findByText("Riktlinjer.pdf");
  });

  it("can retry a failed checkpoint load", async () => {
    const active = vi
      .fn()
      .mockRejectedValueOnce(new Error("Load failed"))
      .mockResolvedValueOnce(buildCheckpoint("awaiting_review", 1));
    const eneo = buildEneo({ activeCheckpoint: null, active });

    render(FlowRunReviewCheckpointPanel, {
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Eneo }
    });

    await screen.findByText(m.flow_run_review_load_failed());
    await fireEvent.click(screen.getByRole("button", { name: m.flow_retry() }));

    await screen.findByText(m.flow_run_review_state_awaiting_review());
    expect(active).toHaveBeenCalledTimes(2);
  });

  it("shows stale edit errors from the checkpoint revision contract", async () => {
    const staleError = new EneoError(
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
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Eneo }
    });

    const valueEditor = await screen.findByLabelText("Answer");
    await fireEvent.input(valueEditor, { target: { value: "Edited answer." } });
    await fireEvent.click(screen.getByRole("button", { name: m.flow_run_review_save_edit() }));

    await screen.findByText(m.flow_error_flow_review_stale_revision());
    expect(edit).toHaveBeenCalledWith({
      flowId: "flow-1",
      runId: "run-1",
      checkpointId: "checkpoint-1",
      expectedCheckpointRevision: 1,
      editedValue: { answer: "Edited answer." }
    });
  });

  it("shows expired review errors from the shared Flow API error contract", async () => {
    const expiredError = new EneoError(
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
      { endpoint: "POST@/review-checkpoints/checkpoint-1/approve-and-continue" }
    );
    const approveAndContinue = vi.fn(async () => {
      throw expiredError;
    });
    const eneo = buildEneo({
      activeCheckpoint: buildCheckpoint("awaiting_review", 1),
      approveAndContinue
    });

    render(FlowRunReviewCheckpointPanel, {
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Eneo }
    });

    await screen.findByText(m.flow_run_review_state_awaiting_review());
    await fireEvent.click(
      screen.getByRole("button", { name: m.flow_transcript_editor_approve_continue() })
    );

    await screen.findByText(m.flow_error_flow_review_expired());
  });

  it("shows typed contract edit errors from the shared Flow API error contract", async () => {
    const contractError = new EneoError(
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
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Eneo }
    });

    const valueEditor = await screen.findByLabelText("Answer");
    await fireEvent.input(valueEditor, { target: { value: "Edited answer." } });
    await fireEvent.click(screen.getByRole("button", { name: m.flow_run_review_save_edit() }));

    await screen.findByText(m.flow_error_typed_io_contract_violation());
    expect(screen.queryByText("backend readable fallback")).toBeNull();
  });

  it("keeps malformed JSON values out of edit requests", async () => {
    const edit = vi.fn();
    const eneo = buildEneo({ activeCheckpoint: buildCheckpoint("awaiting_review", 1), edit });

    render(FlowRunReviewCheckpointPanel, {
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Eneo }
    });

    await fireEvent.click(
      await screen.findByRole("button", { name: m.flow_run_review_show_json() })
    );
    const valueEditor = screen.getByLabelText(m.flow_run_review_json_payload());
    await fireEvent.input(valueEditor, { target: { value: "{bad" } });
    await fireEvent.click(screen.getByRole("button", { name: m.flow_run_review_save_edit() }));

    expect(screen.getAllByText(m.flow_run_review_payload_invalid()).length).toBeGreaterThan(0);
    await fireEvent.click(
      screen.getByRole("button", { name: m.flow_transcript_editor_approve_continue() })
    );
    expect(eneo.flows.runs.reviewCheckpoints.approveAndContinue).not.toHaveBeenCalled();
    expect(edit).not.toHaveBeenCalled();

    await fireEvent.input(valueEditor, {
      target: { value: '"a bare string is not a JSON step output"' }
    });
    await fireEvent.click(screen.getByRole("button", { name: m.flow_run_review_save_edit() }));

    expect(edit).not.toHaveBeenCalled();
  });

  it("sends a text step's edited string without a JSON envelope", async () => {
    const edit = vi.fn(async () => buildCheckpoint("edited", 2));
    const textCheckpoint = {
      ...buildCheckpoint("awaiting_review", 1),
      output_type: "text" as const,
      output_contract: null,
      original_payload_json: { text: "Draft answer." },
      current_payload_json: { text: "Draft answer." }
    };
    const eneo = buildEneo({ activeCheckpoint: textCheckpoint, edit });

    render(FlowRunReviewCheckpointPanel, {
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Eneo }
    });

    const valueEditor = await screen.findByLabelText(m.flow_run_review_current_payload());
    expect((valueEditor as HTMLTextAreaElement).value).toBe("Draft answer.");
    await fireEvent.input(valueEditor, { target: { value: "Reviewed answer." } });
    await fireEvent.click(screen.getByRole("button", { name: m.flow_run_review_save_edit() }));

    await waitFor(() => expect(edit).toHaveBeenCalledTimes(1));
    expect(edit).toHaveBeenCalledWith({
      flowId: "flow-1",
      runId: "run-1",
      checkpointId: "checkpoint-1",
      expectedCheckpointRevision: 1,
      editedValue: "Reviewed answer."
    });
  });

  it("offers approve and reject but not editing on a view-only checkpoint", async () => {
    const edit = vi.fn();
    const viewCheckpoint = {
      ...buildCheckpoint("awaiting_review", 1),
      review_mode: "view" as const
    };
    const eneo = buildEneo({ activeCheckpoint: viewCheckpoint, edit });

    render(FlowRunReviewCheckpointPanel, {
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Eneo }
    });

    await screen.findByText(m.flow_run_review_view_only());
    expect(
      (screen.getByRole("button", { name: m.flow_run_review_save_edit() }) as HTMLButtonElement)
        .disabled
    ).toBe(true);
    expect(
      (
        screen.getByRole("button", {
          name: m.flow_transcript_editor_approve_continue()
        }) as HTMLButtonElement
      ).disabled
    ).toBe(false);
    expect(edit).not.toHaveBeenCalled();
  });

  it("approves and continues the run with one request", async () => {
    const resumedCheckpoint = buildCheckpoint("resumed", 3);
    const approve = vi.fn();
    const resume = vi.fn();
    const approveAndContinue = vi.fn(async () => ({
      checkpoint: resumedCheckpoint,
      run: buildRun("queued")
    }));
    const onChanged = vi.fn();
    const eneo = buildEneo({
      activeCheckpoint: buildCheckpoint("awaiting_review", 1),
      approve,
      approveAndContinue,
      resume
    });

    render(FlowRunReviewCheckpointPanel, {
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Eneo, onChanged }
    });

    await screen.findByText(m.flow_run_review_state_awaiting_review());
    expect(screen.queryByRole("button", { name: m.flow_run_review_resume() })).toBeNull();

    // Approving is the decision and continuing is its consequence, so one
    // press is one request: the server approves and resumes in a single
    // transaction, and the key is bound to the revision the reviewer saw.
    await fireEvent.click(
      screen.getByRole("button", { name: m.flow_transcript_editor_approve_continue() })
    );

    await waitFor(() => expect(approveAndContinue).toHaveBeenCalledTimes(1));
    expect(approveAndContinue).toHaveBeenCalledWith({
      flowId: "flow-1",
      runId: "run-1",
      checkpointId: "checkpoint-1",
      expectedCheckpointRevision: 1,
      idempotencyKey: "flow-review-continue:checkpoint-1:1"
    });
    expect(approve).not.toHaveBeenCalled();
    expect(resume).not.toHaveBeenCalled();
    await screen.findByText(m.flow_run_review_state_resumed());
    expect(screen.queryByRole("button", { name: m.flow_run_review_resume() })).toBeNull();
    expect(onChanged).toHaveBeenCalled();
  });

  it("keeps the decision open and retries with the same key when the request fails", async () => {
    // Nothing is stored when the combined request fails, so the checkpoint is
    // still awaiting review and the same button is the retry. The retry
    // reuses the key: a request whose response was lost replays server-side
    // instead of failing on a revision the reviewer never saw.
    const approveAndContinue = vi
      .fn()
      .mockRejectedValueOnce(new Error("worker unavailable"))
      .mockResolvedValueOnce({
        checkpoint: buildCheckpoint("resumed", 3),
        run: buildRun("queued")
      });
    const eneo = buildEneo({
      activeCheckpoint: buildCheckpoint("awaiting_review", 1),
      approveAndContinue
    });

    render(FlowRunReviewCheckpointPanel, {
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Eneo }
    });

    await screen.findByText(m.flow_run_review_state_awaiting_review());
    await fireEvent.click(
      screen.getByRole("button", { name: m.flow_transcript_editor_approve_continue() })
    );

    await screen.findByText(m.flow_run_review_approve_failed());
    expect(screen.getByText(m.flow_run_review_state_awaiting_review())).toBeTruthy();
    expect(screen.queryByRole("button", { name: m.flow_run_review_resume() })).toBeNull();
    const retry = screen.getByRole("button", { name: m.flow_transcript_editor_approve_continue() });
    await waitFor(() => expect((retry as HTMLButtonElement).disabled).toBe(false));
    await fireEvent.click(retry);

    await waitFor(() => expect(approveAndContinue).toHaveBeenCalledTimes(2));
    expect(approveAndContinue.mock.calls[0][0].idempotencyKey).toBe(
      approveAndContinue.mock.calls[1][0].idempotencyKey
    );
    await screen.findByText(m.flow_run_review_state_resumed());
  });

  it("shows the review deadline and blocks decision actions after it passes", async () => {
    const expiredCheckpoint = {
      ...buildCheckpoint("awaiting_review", 1),
      expires_at: "2000-01-01T10:00:00Z"
    };
    const edit = vi.fn();
    const approveAndContinue = vi.fn();
    const reject = vi.fn();
    const eneo = buildEneo({
      activeCheckpoint: expiredCheckpoint,
      edit,
      approveAndContinue,
      reject
    });

    render(FlowRunReviewCheckpointPanel, {
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Eneo }
    });

    await screen.findByText(m.flow_run_review_deadline_expired());

    expect(
      (screen.getByRole("button", { name: m.flow_run_review_save_edit() }) as HTMLButtonElement)
        .disabled
    ).toBe(true);
    expect(
      (
        screen.getByRole("button", {
          name: m.flow_transcript_editor_approve_continue()
        }) as HTMLButtonElement
      ).disabled
    ).toBe(true);
    expect((screen.getByRole("button", { name: m.reject() }) as HTMLButtonElement).disabled).toBe(
      true
    );

    expect(edit).not.toHaveBeenCalled();
    expect(approveAndContinue).not.toHaveBeenCalled();
    expect(reject).not.toHaveBeenCalled();
  });

  it("shows backend-expired checkpoints as expired and non-editable", async () => {
    const eneo = buildEneo({ activeCheckpoint: buildCheckpoint("expired", 2) });

    render(FlowRunReviewCheckpointPanel, {
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Eneo }
    });

    await screen.findByText(m.flow_run_review_state_expired());
    await screen.findByText(m.flow_run_review_deadline_expired());

    expect(
      (screen.getByRole("button", { name: m.flow_run_review_save_edit() }) as HTMLButtonElement)
        .disabled
    ).toBe(true);
    expect(
      (
        screen.getByRole("button", {
          name: m.flow_transcript_editor_approve_continue()
        }) as HTMLButtonElement
      ).disabled
    ).toBe(true);
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
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Eneo }
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
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Eneo }
    });

    await screen.findByText(m.flow_run_review_deadline_approved());
    await fireEvent.click(screen.getByRole("button", { name: m.flow_run_review_resume() }));

    await waitFor(() => expect(resume).toHaveBeenCalledTimes(1));
  });

  it("requires and trims the reviewer reject reason", async () => {
    const reject = vi.fn(async () => buildCheckpoint("rejected", 2));
    const eneo = buildEneo({ activeCheckpoint: buildCheckpoint("awaiting_review", 1), reject });

    render(FlowRunReviewCheckpointPanel, {
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Eneo }
    });

    await screen.findByText(m.flow_run_review_state_awaiting_review());
    const disclosure = screen.getByText(m.flow_run_review_reject_open()).closest("details");
    expect(disclosure?.open).toBe(false);
    expect(disclosure?.contains(screen.getByLabelText(m.flow_run_review_reject_reason()))).toBe(
      true
    );
    if (!disclosure) throw new Error("Missing rejection disclosure");
    disclosure.open = true;
    await fireEvent(disclosure, new Event("toggle"));
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
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Eneo }
    });

    await screen.findByText(m.flow_run_review_state_resumed());

    expect(
      (screen.getByRole("button", { name: m.flow_run_review_save_edit() }) as HTMLButtonElement)
        .disabled
    ).toBe(true);
    expect(
      (
        screen.getByRole("button", {
          name: m.flow_transcript_editor_approve_continue()
        }) as HTMLButtonElement
      ).disabled
    ).toBe(true);
    expect((screen.getByRole("button", { name: m.reject() }) as HTMLButtonElement).disabled).toBe(
      true
    );
    expect(screen.queryByRole("button", { name: m.flow_run_review_resume() })).toBeNull();
  });
});

describe("FlowRunReviewCheckpointPanel speaker mapping", () => {
  function buildSpeakerCheckpoint(): FlowRunReviewCheckpoint {
    return {
      ...buildCheckpoint("awaiting_review", 1),
      output_type: "json",
      current_payload_json: {
        text: "[00:00:00 - 00:00:04] SPEAKER_00: Hej.\n[00:00:05 - 00:00:09] SPEAKER_01: Hallå.",
        structured: {
          speakers: [
            { label: "SPEAKER_00", name: "Anna", confidence: "high", evidence: "" },
            { label: "SPEAKER_01", name: null, confidence: "low", evidence: "" }
          ]
        },
        speaker_mapping: {
          source_step_id: "step-0",
          source_step_order: 1,
          participants: ["Anna", "Bo"],
          inventory: [
            { label: "SPEAKER_00", line_count: 1, samples: ["Hej."] },
            { label: "SPEAKER_01", line_count: 1, samples: ["Hallå."] }
          ]
        }
      }
    };
  }

  it.each([false, true])(
    "approval waits for corrections; failed save blocks downstream execution (%s)",
    async (fails) => {
      let release!: (value: unknown) => void;
      const checkpoint = buildSpeakerCheckpoint();
      const approveAndContinue = vi.fn(async () => ({
        checkpoint: { ...checkpoint, state: "resumed" as const, revision: 3 },
        run: buildRun("queued")
      }));
      const steps = vi.fn(async () => [
        {
          step_id: "step-0",
          step_order: 1,
          runtime_input_file_ids: ["file-1"],
          input_payload_json: {
            transcription: {
              file_ids: ["file-1"],
              source: { attempt_no: 1 },
              segments_hash: "a".repeat(64),
              segments: [
                {
                  file_index: 0,
                  start: 0,
                  end: 4,
                  speaker: "SPEAKER_00",
                  speaker_attribution: "provisional",
                  text: "Hej."
                }
              ]
            }
          }
        }
      ]);
      const eneo = buildEneo({ activeCheckpoint: checkpoint, steps, approveAndContinue });
      const save = vi.fn(
        () =>
          new Promise((resolve) => {
            release = resolve;
          })
      );
      eneo.flows.runs.transcriptCorrections.save = save as never;
      render(FlowRunReviewCheckpointPanel, {
        flowId: "flow-1",
        runId: "run-1",
        eneo: eneo as unknown as Eneo
      });
      const passage = await screen.findByRole("button", { name: /Markera hela passagen: Hej/ });
      await waitFor(() =>
        expect(
          (screen.getByRole("button", { name: "Bekräfta alla förslag (1)" }) as HTMLButtonElement)
            .disabled
        ).toBe(false)
      );
      await fireEvent.click(passage);
      await fireEvent.click(screen.getByRole("button", { name: "Bekräfta Anna" }));
      await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
      await fireEvent.click(screen.getByRole("button", { name: "Godkänn och fortsätt" }));
      expect(approveAndContinue).not.toHaveBeenCalled();
      release({ revision: 1, stale: fails, occurrences: [], speaker_edits: [] });
      if (fails) {
        await screen.findByText("Hämta osparade rättningar");
        expect(approveAndContinue).not.toHaveBeenCalled();
      } else {
        await waitFor(() => expect(approveAndContinue).toHaveBeenCalledTimes(1));
        expect(approveAndContinue).toHaveBeenCalledWith(
          expect.objectContaining({
            expectedCheckpointRevision: 1,
            idempotencyKey: "flow-review-continue:checkpoint-1:1"
          })
        );
      }
    }
  );

  it("keeps a speaker-mapping checkpoint retryable with the same key after a failed request", async () => {
    const checkpoint = buildSpeakerCheckpoint();
    const approveAndContinue = vi
      .fn()
      .mockRejectedValueOnce(new Error("unavailable"))
      .mockResolvedValueOnce({
        checkpoint: { ...checkpoint, state: "resumed", revision: 3 },
        run: buildRun("queued")
      });
    const eneo = buildEneo({
      activeCheckpoint: checkpoint,
      approveAndContinue,
      steps: vi.fn(async () => [
        {
          step_id: "step-0",
          step_order: 1,
          input_payload_json: {
            transcription: {
              file_ids: ["file-1"],
              source: { attempt_no: 1 },
              segments: [{ file_index: 0, start: 0, end: 4, speaker: "SPEAKER_00", text: "Hej." }]
            }
          }
        }
      ])
    });
    render(FlowRunReviewCheckpointPanel, {
      flowId: "flow-1",
      runId: "run-1",
      eneo: eneo as unknown as Eneo
    });
    const button = await screen.findByRole("button", { name: "Godkänn och fortsätt" });
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false));
    await fireEvent.click(button);
    await screen.findByText(m.flow_run_review_approve_failed());
    const retry = screen.getByRole("button", { name: "Godkänn och fortsätt" });
    await waitFor(() => expect((retry as HTMLButtonElement).disabled).toBe(false));
    await fireEvent.click(retry);
    await waitFor(() => expect(approveAndContinue).toHaveBeenCalledTimes(2));
    expect(approveAndContinue.mock.calls[0][0].idempotencyKey).toBe(
      approveAndContinue.mock.calls[1][0].idempotencyKey
    );
  });

  beforeEach(() => {
    vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(() => Promise.resolve());
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  });

  it("plays the transcription step's audio next to the transcript", async () => {
    const steps = vi.fn(async () => [
      {
        step_id: "step-0",
        step_order: 1,
        runtime_input_file_ids: ["file-1"],
        input_payload_json: {
          transcription: {
            file_ids: ["file-1"],
            source: { attempt_no: 1 },
            segments: [
              { file_index: 0, start: 0, end: 4, speaker: "SPEAKER_00", text: "Hej." },
              { file_index: 0, start: 5, end: 9, speaker: "SPEAKER_01", text: "Hallå." }
            ]
          }
        }
      }
    ]);
    const inputFileSignedUrl = vi.fn(async () => ({
      url: "https://app.test/api/v1/files/file-1/download/?token=t",
      expires_at: 4102444800
    }));
    const eneo = buildEneo({
      activeCheckpoint: buildSpeakerCheckpoint(),
      steps,
      inputFileSignedUrl
    });

    render(FlowRunReviewCheckpointPanel, {
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Eneo }
    });

    await screen.findAllByPlaceholderText("Välj eller skriv namn");
    await waitFor(() =>
      expect(inputFileSignedUrl).toHaveBeenCalledWith(
        expect.objectContaining({ flowId: "flow-1", runId: "run-1", fileId: "file-1" })
      )
    );
    expect(inputFileSignedUrl).toHaveBeenCalledTimes(1);
    // Stored segments carry raw labels; the proposed name shows on them.
    const line = await screen.findByText("Hej.");
    expect(line.closest("[data-turn-index]")?.textContent).toContain("Anna");
    expect(screen.getByText("Hallå.").closest("[data-turn-index]")?.textContent).toContain(
      "Talare 2"
    );
    expect(screen.getByRole("button", { name: "00:00" }).hasAttribute("disabled")).toBe(false);
  });

  it("keeps the transcript visible and retries when audio context cannot be loaded", async () => {
    const steps = vi.fn().mockRejectedValueOnce(new Error("boom")).mockResolvedValueOnce([]);
    const eneo = buildEneo({
      activeCheckpoint: buildSpeakerCheckpoint(),
      steps
    });

    render(FlowRunReviewCheckpointPanel, {
      props: { flowId: "flow-1", runId: "run-1", eneo: eneo as unknown as Eneo }
    });

    await screen.findByText("Hej.");
    await screen.findByText(m.flow_run_review_audio_context_failed());

    await fireEvent.click(screen.getByRole("button", { name: m.flow_retry() }));
    await waitFor(() => expect(steps).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(screen.queryByText(m.flow_run_review_audio_context_failed())).toBeNull()
    );
  });
});
