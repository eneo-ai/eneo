// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { focusManager } from "@tanstack/react-query";
import { Suspense } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import type { Permission } from "@/lib/auth/permissions";
import { expectNoAxeViolations } from "@/test/axe";
import { router } from "@/test/navigation";
import { renderInApp, testAppContext, testQueryClient } from "@/test/render";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import { makeFlow } from "../flow-fixtures";
import { flowKeys } from "../flows-api";
import {
  makeCheckpoint,
  makeResultFile,
  makeRunDetail,
  makeRunGraph,
  makeRunStep,
  makeRunSummary
} from "./run-fixtures";
import type { RunDetail, RunSummary } from "./runs-api";

const state = vi.hoisted(() => ({
  announce: vi.fn(),
  routes: {} as Record<string, (init: never) => { status?: number; body: unknown }>,
  stub: null as unknown as ReturnType<typeof import("../editor/testing/fixtures").apiStub>
}));

vi.mock("@/lib/api/browser", async () => {
  const { apiStub } = await import("../editor/testing/fixtures");
  state.stub = apiStub(new Proxy({}, { get: (_target, key: string) => state.routes[key] }));
  return { browserApi: state.stub.client };
});
vi.mock("next/navigation", () => import("@/test/navigation"));
vi.mock("@astryxdesign/core/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@astryxdesign/core/hooks")>()),
  useAnnounce: () => state.announce
}));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  const { makeSpace: space } = await import("@/features/spaces/testing/space-fixture");
  return { useSpace: () => useSpaceFromQuery(() => space({})) };
});

import { FlowRunPage } from "./run-page";

const STATUS = "GET /api/v1/flows/{id}/runs/{run_id}/status/";
const GRAPH = "GET /api/v1/flows/{id}/graph/";
const DETAIL = "GET /api/v1/flows/{id}/runs/{run_id}/";
const STEPS = "GET /api/v1/flows/{id}/runs/{run_id}/steps/";
const REVIEW = "GET /api/v1/flows/{id}/runs/{run_id}/review-checkpoints/active/";
const EVIDENCE = "GET /api/v1/flows/{id}/runs/{run_id}/evidence/";

const graph = makeRunGraph([
  { order: 1, label: "Sammanfatta", status: "completed" },
  { order: 2, label: "Skriv svar", status: "completed" }
]);

function answerRun(summary: RunSummary, detail: RunDetail = makeRunDetail(summary)) {
  state.routes[STATUS] = () => ({ body: summary });
  state.routes[GRAPH] = () => ({ body: graph });
  state.routes[DETAIL] = () => ({ body: detail });
  state.routes[STEPS] = () => ({ body: [makeRunStep(1), makeRunStep(2)] });
}

function answerEvidence() {
  state.routes[EVIDENCE] = () => ({
    body: {
      run: makeRunSummary(),
      debug_export: {
        run: { run_id: "run-1", summary: null },
        security: { redaction_applied: false }
      },
      step_attempts: [],
      provider_calls: {
        count: 0,
        items: [],
        has_more: false,
        next_after_event_id: null,
        total_count: 0
      },
      knowledge_traces: []
    }
  });
}

function calls(route: string) {
  return state.stub.calls.filter((call) => `${call.method} ${call.path}` === route);
}

/** The person leaves the tab and comes back to it, after the app's 30 s. */
async function comeBack() {
  await act(() => vi.advanceTimersByTimeAsync(31_000));
  act(() => {
    focusManager.setFocused(false);
    focusManager.setFocused(true);
  });
  focusManager.setFocused(undefined);
  await act(() => vi.advanceTimersByTimeAsync(100));
}

function renderRun(permissions: Permission[] = ["flows_view", "flows_run"]) {
  const queryClient = testQueryClient();
  const flow = makeFlow({ published_version: 3 });
  queryClient.setQueryData(flowKeys.flow(flow.id), flow);
  queryClient.setQueryData(["spaces", "space-1"], makeSpace({}));
  return renderInApp(
    <Suspense>
      <FlowRunPage flowId="flow-1" runId="run-1" />
    </Suspense>,
    { queryClient, appContext: testAppContext({ permissions }) }
  );
}

beforeEach(() => {
  state.routes = {};
});

afterEach(() => {
  cleanup();
  state.stub.calls.length = 0;
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("FlowRunPage", () => {
  it("shows a finished run's result, its steps and what it used", async () => {
    answerRun(makeRunSummary());
    const { container } = renderRun();

    expect(await screen.findByText("Beslutet är fattat.")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1 })).toBeTruthy();
    const steps = screen.getByRole("heading", { level: 2, name: messages.flow_runs_steps_heading });
    expect(steps).toBeTruthy();
    const first = await screen.findByRole("article", { name: "Steg 1: Sammanfatta" });
    expect(within(first).getByText("Resultat från steg 1")).toBeTruthy();
    expect(within(first).getByText(messages.flow_runs_step_status_completed)).toBeTruthy();
    expect(screen.getByText(/^1\s500 totalt \(1\s200 in, 300 ut\)/)).toBeTruthy();
    expect(screen.getByText(messages.flow_runs_usage_tokens_explainer)).toBeTruthy();
    expect(screen.getByText("Startad av Anna Lind")).toBeTruthy();
    expect(screen.queryByRole("button", { name: messages.flow_runs_cancel })).toBeNull();
    await expectNoAxeViolations(container);
  });

  it("offers neither knowledge nor trace when the core would not let the caller read the evidence", async () => {
    const summary = makeRunSummary();
    answerRun(
      summary,
      makeRunDetail({
        ...summary,
        evidence_access: {
          can_read_evidence: false,
          can_export_redacted: false,
          can_export_raw: false,
          read_refusal_code: "insufficient_tenant_permission",
          redacted_export_refusal_code: "insufficient_tenant_permission",
          raw_export_refusal_code: "insufficient_tenant_permission"
        }
      })
    );
    renderRun(["flows_view", "flows_run", "flows_trace", "admin"]);

    expect(await screen.findByText("Beslutet är fattat.")).toBeTruthy();
    expect(
      screen.queryByRole("heading", { name: messages.flow_runs_knowledge_heading })
    ).toBeNull();
    expect(
      screen.queryByRole("heading", { name: messages.flow_run_extras_trace_heading })
    ).toBeNull();
  });

  it("says why a run failed in the catalog's words and offers a retry", async () => {
    const failed = makeRunSummary({ status: "failed" });
    answerRun(
      failed,
      makeRunDetail({
        ...failed,
        result: null,
        error: {
          code: "flow_step_timeout",
          message: "step 2 timed out",
          details: null,
          retryable: false
        }
      } as Partial<RunDetail>)
    );
    state.routes["POST /api/v1/flows/{id}/runs/{run_id}/retry/"] = () => ({
      status: 201,
      body: {
        created: true,
        first_executed_step_order: 2,
        reused_step_orders: [1],
        source_run_id: "run-1",
        run: makeRunSummary({ id: "run-2", status: "queued" })
      }
    });
    const { container } = renderRun();

    expect(await screen.findByText(messages.flow_error_flow_step_timeout)).toBeTruthy();
    expect(screen.queryByText("step 2 timed out")).toBeNull();
    await expectNoAxeViolations(container);

    fireEvent.click(screen.getByRole("button", { name: messages.flow_runs_retry }));
    await waitFor(() =>
      expect(router.push).toHaveBeenCalledWith("/spaces/space-1/flows/flow-1/runs/run-2")
    );
    const retry = calls("POST /api/v1/flows/{id}/runs/{run_id}/retry/")[0];
    expect(
      (retry?.init as { params?: { header?: Record<string, string> } }).params?.header?.[
        "Idempotency-Key"
      ]
    ).toBeTruthy();
  });

  it("says a retry was already started, with a link to it, instead of opening it", async () => {
    const failed = makeRunSummary({ status: "failed" });
    answerRun(failed, makeRunDetail({ ...failed, result: null } as Partial<RunDetail>));
    state.routes["POST /api/v1/flows/{id}/runs/{run_id}/retry/"] = () => ({
      status: 200,
      body: {
        created: false,
        first_executed_step_order: 2,
        reused_step_orders: [1],
        source_run_id: "run-1",
        run: makeRunSummary({ id: "run-2", status: "completed" })
      }
    });
    renderRun();

    fireEvent.click(await screen.findByRole("button", { name: messages.flow_runs_retry }));
    expect(await screen.findByText(messages.flow_runs_retry_replayed)).toBeTruthy();
    const link = screen.getByRole("link", { name: messages.flow_runs_retry_replayed_open });
    expect(link.getAttribute("href")).toBe("/spaces/space-1/flows/flow-1/runs/run-2");
    expect(router.push).not.toHaveBeenCalled();
  });

  it("guides a failed run with its error's facts and keeps the technical detail closed", async () => {
    const failed = makeRunSummary({ status: "failed" });
    answerRun(
      failed,
      makeRunDetail({
        ...failed,
        result: null,
        error: {
          code: "flow_step_timeout",
          message: "step 2 timed out after 300s",
          step_order: 2,
          details: {
            step_description: "Skriv svar",
            phase: "provider_request",
            provider_work_may_have_completed: true
          },
          retryable: true
        }
      } as Partial<RunDetail>)
    );
    const { container } = renderRun();

    expect(await screen.findByText("Körningen stannade i steg 2: Skriv svar.")).toBeTruthy();
    expect(screen.getByText(messages.flow_run_extras_failure_provider_unknown)).toBeTruthy();
    expect(screen.getByText(messages.flow_run_extras_failure_retryable)).toBeTruthy();
    expect(screen.queryByText("step 2 timed out after 300s")).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: messages.flow_run_extras_failure_technical })
    );
    expect(screen.getByText("step 2 timed out after 300s")).toBeTruthy();
    expect(screen.getByText("flow_step_timeout")).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("shows a step's prompt and model settings when asked, and the run's webhook deliveries", async () => {
    const summary = makeRunSummary();
    answerRun(
      summary,
      makeRunDetail({
        ...summary,
        webhook_deliveries: [
          {
            id: "delivery-1",
            step_id: "step-2",
            step_order: 2,
            attempt_no: 1,
            delivery_status: "dead_lettered",
            delivery_attempts: 5,
            dead_lettered_at: "2026-10-21T09:00:00Z",
            created_at: "2026-10-21T08:01:00Z",
            updated_at: "2026-10-21T09:00:00Z"
          }
        ]
      })
    );
    state.routes[STEPS] = () => ({
      body: [
        makeRunStep(1, {
          effective_prompt: "Sammanfatta ärendet: Bygglov",
          effective_prompt_truncated: true,
          model_parameters_json: { temperature: 0.2 }
        }),
        makeRunStep(2)
      ]
    });
    const { container } = renderRun();

    const first = await screen.findByRole("article", { name: "Steg 1: Sammanfatta" });
    expect(within(first).queryByText("Sammanfatta ärendet: Bygglov")).toBeNull();
    fireEvent.click(
      await within(first).findByRole("button", { name: messages.flow_run_extras_prompt_heading })
    );
    expect(within(first).getByText("Sammanfatta ärendet: Bygglov")).toBeTruthy();
    expect(within(first).getByText(messages.flow_run_extras_prompt_truncated)).toBeTruthy();
    expect(within(first).getByText("temperature")).toBeTruthy();
    expect(
      within(first).getByRole("button", { name: messages.flow_run_more_copy_prompt })
    ).toBeTruthy();
    const second = screen.getByRole("article", { name: "Steg 2: Skriv svar" });
    expect(
      within(second).queryByRole("button", { name: messages.flow_run_extras_prompt_heading })
    ).toBeNull();

    const deliveries = screen.getByRole("table", {
      name: messages.flow_run_extras_webhook_heading
    });
    const row = within(deliveries).getAllByRole("row")[1]!;
    expect(within(row).getByText("Steg 2: Skriv svar")).toBeTruthy();
    expect(within(row).getByText(messages.flow_run_extras_webhook_dead_lettered)).toBeTruthy();
    expect(within(row).getByText("5")).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("names the files a step received, with a download for each", async () => {
    answerRun(makeRunSummary());
    state.routes[STEPS] = () => ({
      body: [
        makeRunStep(1, {
          runtime_input_file_ids: ["file-a", "file-b"],
          runtime_input_files: [
            { file_id: "file-a", name: "underlag.pdf", mimetype: "application/pdf" }
          ]
        }),
        makeRunStep(2)
      ]
    });
    const { container } = renderRun();

    const first = await screen.findByRole("article", { name: "Steg 1: Sammanfatta" });
    const files = await within(first).findByRole("list", {
      name: messages.flow_runs_step_input_files
    });
    expect(within(files).getByText("underlag.pdf")).toBeTruthy();
    expect(within(files).getByText("PDF")).toBeTruthy();
    expect(within(files).getByText("Fil 2")).toBeTruthy();
    expect(within(files).getByRole("button", { name: "Ladda ned underlag.pdf" })).toBeTruthy();
    expect(within(files).getByRole("button", { name: "Ladda ned fil 2" })).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("says up front that only the one who started a failed run can run it again", async () => {
    answerRun(
      makeRunSummary({
        status: "failed",
        started_by: {
          principal_type: "user",
          id: "user-2",
          display_name: "Erik Berg",
          email: "erik.berg@example.se"
        }
      })
    );
    const { container } = renderRun();

    expect(
      await screen.findByText(messages.flow_runs_retry_starter_only.replace("{name}", "Erik Berg"))
    ).toBeTruthy();
    expect(screen.getByText("Startad av Erik Berg")).toBeTruthy();
    expect(screen.queryByRole("button", { name: messages.flow_runs_retry })).toBeNull();
    await expectNoAxeViolations(container);
  });

  it("does not offer a retry of a run of an earlier version, and says why", async () => {
    answerRun(makeRunSummary({ status: "failed", flow_version: 2 }));
    renderRun();
    expect(await screen.findByText(messages.flow_runs_retry_version_changed)).toBeTruthy();
    expect(screen.queryByRole("button", { name: messages.flow_runs_retry })).toBeNull();
  });

  it("cancels a running run after asking, and says what the core answered", async () => {
    const running = makeRunSummary({ status: "running", finished_at: null });
    answerRun(running, makeRunDetail({ ...running, result: null }));
    state.routes["POST /api/v1/flows/{id}/runs/{run_id}/cancel/"] = () => ({
      body: makeRunSummary({ status: "cancelled" })
    });
    renderRun();

    fireEvent.click(await screen.findByRole("button", { name: messages.flow_runs_cancel }));
    const dialog = await screen.findByRole("alertdialog", {
      name: messages.flow_runs_cancel_title
    });
    const cancelled = makeRunSummary({ status: "cancelled" });
    answerRun(cancelled, makeRunDetail({ ...cancelled, result: null }));
    fireEvent.click(within(dialog).getByRole("button", { name: messages.flow_runs_cancel }));

    await waitFor(() =>
      expect(state.announce).toHaveBeenCalledWith(messages.flow_runs_cancel_done)
    );
    expect(calls("POST /api/v1/flows/{id}/runs/{run_id}/cancel/")).toHaveLength(1);
    // The button goes with the run's state; focus moves to the page's heading.
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: messages.flow_runs_cancel })).toBeNull()
    );
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole("heading", { level: 1 }))
    );
  });

  it("reads the whole run again when asked, and says so", async () => {
    answerRun(makeRunSummary());
    renderRun();
    await screen.findByText("Beslutet är fattat.");
    expect(calls(DETAIL)).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: messages.flow_run_more_refresh }));

    await waitFor(() =>
      expect(state.announce).toHaveBeenCalledWith(messages.flow_run_more_refreshed)
    );
    expect(calls(STATUS)).toHaveLength(2);
    expect(calls(DETAIL)).toHaveLength(2);
    expect(calls(STEPS)).toHaveLength(2);
  });

  it("copies the run's id and trace id for support", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    answerRun(makeRunSummary());
    renderRun();
    await screen.findByText("Beslutet är fattat.");
    expect(screen.getByText("trace-1")).toBeTruthy();

    fireEvent.click(
      screen.getByRole("button", {
        name: messages.chat_debug_copy_value.replace("{label}", messages.flow_run_more_trace_id)
      })
    );
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("trace-1"));
    fireEvent.click(
      screen.getByRole("button", {
        name: messages.chat_debug_copy_value.replace("{label}", messages.flow_run_more_run_id)
      })
    );
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("run-1"));
  });

  it("explains what the run id and the trace id are for", async () => {
    answerRun(makeRunSummary());
    const { container } = renderRun();
    await screen.findByText("Beslutet är fattat.");

    for (const [label, hint] of [
      [messages.flow_run_more_run_id, messages.flow_run_more_run_id_hint],
      [messages.flow_run_more_trace_id, messages.flow_run_more_trace_id_hint]
    ] as const) {
      const about = screen.getByRole("button", {
        name: messages.chat_debug_value_about.replace("{label}", label)
      });
      fireEvent.focus(about);
      expect(await screen.findByText(hint)).toBeTruthy();
      fireEvent.blur(about);
    }
    await expectNoAxeViolations(container);
  });

  it("offers every other file the run made beside its result", async () => {
    const summary = makeRunSummary();
    answerRun(
      summary,
      makeRunDetail({
        ...summary,
        result: { kind: "inline_text", text: "Beslutet är fattat." },
        result_files: [makeResultFile({ file_id: "file-7", name: "underlag.docx" })]
      })
    );
    const { container } = renderRun();
    const files = await screen.findByRole("list", { name: messages.flow_run_more_other_files });
    expect(within(files).getByText("underlag.docx")).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("follows a moving run through its status alone, and reads the detail again only when it moved", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const running = makeRunSummary({ status: "running", finished_at: null, revision: 2 });
    answerRun(running, makeRunDetail({ ...running, result: null }));
    renderRun();
    await screen.findByText(messages.flow_runs_result_pending);
    expect(calls(DETAIL)).toHaveLength(1);

    await act(() => vi.advanceTimersByTimeAsync(2_100));
    expect(calls(STATUS)).toHaveLength(2);
    expect(calls(DETAIL)).toHaveLength(1);

    answerRun(makeRunSummary({ revision: 3 }));
    await act(() => vi.advanceTimersByTimeAsync(2_100));
    expect(await screen.findByText("Beslutet är fattat.")).toBeTruthy();
    expect(calls(DETAIL)).toHaveLength(2);
    expect(state.announce).toHaveBeenCalledWith(
      messages.flow_runs_status_now.replace("{status}", messages.flow_runs_status_completed)
    );

    await act(() => vi.advanceTimersByTimeAsync(20_000));
    expect(calls(STATUS)).toHaveLength(3);
  });

  it("reads the trace once more when the run it was read from ends, and keeps it from then on", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const running = makeRunSummary({ status: "running", finished_at: null, revision: 2 });
    answerRun(running, makeRunDetail({ ...running, result: null }));
    answerEvidence();
    renderRun();
    fireEvent.click(
      await screen.findByRole("button", { name: messages.flow_run_extras_trace_show })
    );
    await screen.findByRole("button", { name: messages.flow_run_extras_debug_copy });
    expect(calls(EVIDENCE)).toHaveLength(1);

    answerRun(makeRunSummary({ revision: 3 }));
    await act(() => vi.advanceTimersByTimeAsync(2_100));
    expect(await screen.findByText("Beslutet är fattat.")).toBeTruthy();
    await waitFor(() => expect(calls(EVIDENCE)).toHaveLength(2));

    await comeBack();
    expect(calls(EVIDENCE)).toHaveLength(2);
  });

  describe("review", () => {
    function answerReview(checkpoint = makeCheckpoint()) {
      const waiting = makeRunSummary({ status: "awaiting_review", finished_at: null });
      answerRun(waiting, makeRunDetail({ ...waiting, result: null }));
      state.routes[REVIEW] = () => ({ body: checkpoint });
    }

    it("approves the reviewer's correction and lets the run go on", async () => {
      answerReview();
      state.routes["PATCH /api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/"] =
        () => ({ body: makeCheckpoint({ revision: 2, state: "edited" }) });
      state.routes[
        "POST /api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/approve-and-continue/"
      ] = () => ({
        body: { checkpoint: makeCheckpoint({ state: "resumed" }), run: makeRunSummary() }
      });
      const { container } = renderRun(["flows_view", "flows_manage"]);

      const panel = await screen.findByRole("region", { name: "Granska steg 2: Skriv svar" });
      await expectNoAxeViolations(container);
      fireEvent.change(within(panel).getByLabelText(/^Stegets text/), {
        target: { value: "Hej Anna, tack för ditt brev. Vi återkommer." }
      });
      fireEvent.click(
        within(panel).getByRole("button", { name: messages.flow_runs_review_approve_changed })
      );

      await waitFor(() =>
        expect(state.announce).toHaveBeenCalledWith(messages.flow_runs_review_approved)
      );
      const edit = calls(
        "PATCH /api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/"
      )[0];
      expect(edit?.init.body).toEqual({
        edited_value: "Hej Anna, tack för ditt brev. Vi återkommer.",
        expected_checkpoint_revision: 1
      });
      const approve = calls(
        "POST /api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/approve-and-continue/"
      )[0];
      expect(approve?.init.body).toEqual({ expected_checkpoint_revision: 2 });
      expect(
        (approve?.init as { params?: { header?: Record<string, string> } }).params?.header
      ).toEqual({ "Idempotency-Key": "review-approve:checkpoint-1:2" });
    });

    it("edits a structured output field by field and puts problems at the field", async () => {
      answerReview(
        makeCheckpoint({
          output_type: "json",
          current_payload_json: { structured: { mottagare: "Anna", antal: 2 } },
          original_payload_json: { structured: { mottagare: "Anna", antal: 2 } }
        })
      );
      state.routes["PATCH /api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/"] =
        () => ({
          status: 400,
          body: {
            message: "Review checkpoint step 2 output: 'mottagare' is too short",
            code: "typed_io_contract_violation",
            context: { payload_field: "mottagare" }
          }
        });
      const { container } = renderRun(["flows_view", "flows_manage"]);

      const panel = await screen.findByRole("region", { name: "Granska steg 2: Skriv svar" });
      await expectNoAxeViolations(container);
      const count = within(panel).getByLabelText(/^antal/);
      fireEvent.change(count, { target: { value: "två" } });
      fireEvent.click(within(panel).getByRole("button", { name: messages.flow_runs_review_save }));
      expect(await within(panel).findByText("antal måste vara ett tal.")).toBeTruthy();
      expect(document.activeElement).toBe(count);
      expect(
        calls("PATCH /api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/")
      ).toHaveLength(0);

      fireEvent.change(count, { target: { value: "3" } });
      fireEvent.change(within(panel).getByLabelText(/^mottagare/), { target: { value: "A" } });
      fireEvent.click(within(panel).getByRole("button", { name: messages.flow_runs_review_save }));
      expect(
        await within(panel).findByText(messages.flow_error_typed_io_contract_violation)
      ).toBeTruthy();
      expect(document.activeElement).toBe(within(panel).getByLabelText(/^mottagare/));
      expect(
        calls("PATCH /api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/")[0]?.init
          .body
      ).toEqual({ edited_value: { mottagare: "A", antal: 3 }, expected_checkpoint_revision: 1 });
    });

    it("reviews a speaker mapping as one name per speaker", async () => {
      answerReview(
        makeCheckpoint({
          output_type: "json",
          current_payload_json: {
            structured: {
              speakers: [
                { label: "SPEAKER_00", name: "Anna", confidence: "high", evidence: "Hälsar" },
                { label: "SPEAKER_01", name: null, confidence: "low", evidence: "" }
              ]
            }
          }
        })
      );
      state.routes["PATCH /api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/"] =
        () => ({ body: makeCheckpoint({ revision: 2 }) });
      state.routes[
        "POST /api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/approve-and-continue/"
      ] = () => ({ body: { checkpoint: makeCheckpoint(), run: makeRunSummary() } });
      const { container } = renderRun(["flows_view", "flows_manage"]);

      const panel = await screen.findByRole("region", { name: "Granska steg 2: Skriv svar" });
      expect((within(panel).getByLabelText(/^Namn för SPEAKER_00/) as HTMLInputElement).value).toBe(
        "Anna"
      );
      await expectNoAxeViolations(container);
      fireEvent.change(within(panel).getByLabelText(/^Namn för SPEAKER_01/), {
        target: { value: "Bo" }
      });
      fireEvent.click(
        within(panel).getByRole("button", { name: messages.flow_runs_review_approve_changed })
      );
      await waitFor(() =>
        expect(state.announce).toHaveBeenCalledWith(messages.flow_runs_review_approved)
      );
      expect(
        calls("PATCH /api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/")[0]?.init
          .body
      ).toEqual({
        edited_value: {
          speakers: [
            { label: "SPEAKER_00", name: "Anna", confidence: "high", evidence: "Hälsar" },
            { label: "SPEAKER_01", name: "Bo", confidence: "low", evidence: "" }
          ]
        },
        expected_checkpoint_revision: 1
      });
    });

    it("asks for a reason before rejecting", async () => {
      answerReview();
      state.routes[
        "POST /api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/reject/"
      ] = () => ({ body: makeCheckpoint({ state: "rejected" }) });
      renderRun(["flows_view", "flows_manage"]);

      const panel = await screen.findByRole("region", { name: "Granska steg 2: Skriv svar" });
      fireEvent.click(
        within(panel).getByRole("button", { name: messages.flow_runs_review_reject })
      );
      const confirm = within(panel).getByRole("button", {
        name: messages.flow_runs_review_reject_confirm
      });
      fireEvent.click(confirm);
      expect(
        await within(panel).findByText(messages.flow_runs_review_reject_reason_required)
      ).toBeTruthy();
      expect(document.activeElement).toBe(within(panel).getByLabelText(/^Varför avvisar du/));

      // Over the limit is said at the field, without asking the core.
      fireEvent.change(within(panel).getByLabelText(/^Varför avvisar du/), {
        target: { value: "x".repeat(1025) }
      });
      fireEvent.click(confirm);
      expect(
        await within(panel).findByText(
          messages.flow_runs_review_reject_reason_too_long.replace("{max}", "1024")
        )
      ).toBeTruthy();
      expect(
        calls("POST /api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/reject/")
      ).toHaveLength(0);
      await expectNoAxeViolations(panel);

      fireEvent.change(within(panel).getByLabelText(/^Varför avvisar du/), {
        target: { value: "Fel mottagare" }
      });
      fireEvent.click(confirm);
      await waitFor(() =>
        expect(state.announce).toHaveBeenCalledWith(messages.flow_runs_review_rejected)
      );
      expect(
        calls("POST /api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/reject/")[0]
          ?.init.body
      ).toEqual({ expected_checkpoint_revision: 1, reason: "Fel mottagare" });
    });

    it("shows another reviewer's edit and approval on coming back, though the run did not move", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      answerReview();
      renderRun(["flows_view", "flows_manage"]);
      const region = { name: "Granska steg 2: Skriv svar" };
      const text = () =>
        within(screen.getByRole("region", region)).getByLabelText<HTMLTextAreaElement>(
          /^Stegets text/
        ).value;
      await screen.findByRole("region", region);
      expect(text()).toBe("Hej Anna, tack för ditt brev.");

      // An edit moves the checkpoint and the step's output, not the run.
      state.routes[REVIEW] = () => ({
        body: makeCheckpoint({
          revision: 2,
          state: "edited",
          current_payload_json: { text: "Hej Anna, vi återkommer." }
        })
      });
      await comeBack();
      await waitFor(() => expect(text()).toBe("Hej Anna, vi återkommer."));
      expect(calls(STEPS)).toHaveLength(2);

      // So does approving it without letting the run go on.
      state.routes[REVIEW] = () => ({
        body: makeCheckpoint({
          revision: 3,
          state: "approved",
          current_payload_json: { text: "Hej Anna, vi återkommer." }
        })
      });
      await comeBack();
      expect(
        await screen.findByRole("button", { name: messages.flow_runs_review_resume })
      ).toBeTruthy();
      // The run's detail, read once for its version, is not read again.
      expect(calls(DETAIL)).toHaveLength(1);
    });

    it("offers no decision once the review time has run out", async () => {
      answerReview(makeCheckpoint({ expires_at: "2026-10-01T00:00:00Z" }));
      renderRun(["flows_view", "flows_manage"]);
      expect(await screen.findByText(messages.flow_runs_review_expired_title)).toBeTruthy();
      expect(screen.queryByRole("button", { name: messages.flow_runs_review_approve })).toBeNull();
    });

    it("shows the output to someone who may not review, and says who can", async () => {
      answerReview();
      renderRun(["flows_view", "flows_run"]);
      expect(await screen.findByText(messages.flow_runs_review_not_allowed)).toBeTruthy();
      expect(screen.getByText("Hej Anna, tack för ditt brev.")).toBeTruthy();
      expect(screen.queryByRole("button", { name: messages.flow_runs_review_approve })).toBeNull();
    });
  });

  describe("transcript", () => {
    const SOURCE =
      "GET /api/v1/flows/{flow_id}/runs/{run_id}/steps/{step_id}/attempts/{attempt_no}/transcript-source/";
    const CORRECTIONS = "GET /api/v1/flows/{id}/runs/{run_id}/transcript-corrections/";
    const EDIT = "PATCH /api/v1/flows/{id}/runs/{run_id}/steps/{step_id}/transcript-corrections/";

    function answerAudioRun() {
      answerRun(makeRunSummary());
      state.routes[STEPS] = () => ({
        body: [
          makeRunStep(1, {
            input_payload_json: {
              transcription: { file_ids: ["audio-1"], source: { attempt_no: 1 } }
            }
          }),
          makeRunStep(2)
        ]
      });
      state.routes[SOURCE] = () => ({
        body: {
          status: "present",
          run_id: "run-1",
          step_id: "step-1",
          attempt_no: 1,
          source_hash: "hash-1",
          bounds: { segments_bytes: 1, detail_bytes: 0, words_bytes: 0, segments_count: 2 },
          component_omissions: {},
          start_segment_index: 0,
          page_size: 200,
          max_response_bytes: 1000000,
          next_segment_index: null,
          segments: [
            {
              segment_index: 0,
              file_index: 0,
              start: 0,
              end: 3,
              speaker: "SPEAKER_00",
              text: "Välkomna."
            },
            {
              segment_index: 1,
              file_index: 0,
              start: 65,
              end: 70,
              speaker: "SPEAKER_01",
              text: "Tack."
            }
          ]
        }
      });
      state.routes[CORRECTIONS] = () => ({ body: [] });
    }

    it("shows each line with its time and speaker, and saves the speakers' names", async () => {
      answerAudioRun();
      state.routes[EDIT] = () => ({ body: {} });
      const { container } = renderRun(["flows_view", "flows_manage"]);

      const lines = await screen.findByRole("list", { name: messages.flow_runs_transcript_lines });
      expect(within(lines).getByText("1:05")).toBeTruthy();
      expect(within(lines).getByText("SPEAKER_01")).toBeTruthy();
      await expectNoAxeViolations(container);

      fireEvent.change(screen.getByLabelText("Namn för SPEAKER_00"), { target: { value: "Anna" } });
      fireEvent.click(
        screen.getByRole("button", { name: messages.flow_runs_transcript_names_save })
      );
      await waitFor(() =>
        expect(state.announce).toHaveBeenCalledWith(messages.flow_runs_transcript_names_saved)
      );
      expect(calls(EDIT)[0]?.init.body).toEqual({
        expected_revision: null,
        segments_hash: "hash-1",
        occurrences: [],
        speaker_edits: [],
        speaker_names: { SPEAKER_00: "Anna", SPEAKER_01: null }
      });
    });

    it("reads the run's detail, steps and evidence again on Refresh or when the run moved, never on a refocus", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      answerAudioRun();
      answerEvidence();
      renderRun(["flows_view"]);
      await screen.findByRole("list", { name: messages.flow_runs_transcript_lines });
      fireEvent.click(screen.getByRole("button", { name: messages.flow_run_extras_trace_show }));
      await screen.findByRole("button", { name: messages.flow_run_extras_debug_copy });
      const audited = () => [DETAIL, STEPS, CORRECTIONS, EVIDENCE].map((r) => calls(r).length);
      expect(audited()).toEqual([1, 1, 1, 1]);

      // Back to the tab twice, after the app's 30 s: the content-free status is
      // read again, the run's detail, steps and evidence are not. Corrections,
      // which change on a finished run too, are read once more.
      await act(() => vi.advanceTimersByTimeAsync(31_000));
      for (let i = 0; i < 2; i++) {
        act(() => {
          focusManager.setFocused(false);
          focusManager.setFocused(true);
        });
        await act(() => vi.advanceTimersByTimeAsync(100));
      }
      focusManager.setFocused(undefined);
      await waitFor(() => expect(calls(STATUS)).toHaveLength(2));
      expect(audited()).toEqual([1, 1, 2, 1]);

      fireEvent.click(screen.getByRole("button", { name: messages.flow_run_more_refresh }));
      await waitFor(() =>
        expect(state.announce).toHaveBeenCalledWith(messages.flow_run_more_refreshed)
      );
      expect(audited()).toEqual([2, 2, 3, 2]);

      // The run moved on (a new revision): its detail and steps are read once more.
      state.routes[STATUS] = () => ({ body: makeRunSummary({ revision: 9 }) });
      await act(() => vi.advanceTimersByTimeAsync(31_000));
      act(() => {
        focusManager.setFocused(false);
        focusManager.setFocused(true);
      });
      focusManager.setFocused(undefined);
      await waitFor(() => expect(calls(DETAIL)).toHaveLength(3));
      await waitFor(() => expect(calls(STEPS)).toHaveLength(3));
      await act(() => vi.advanceTimersByTimeAsync(100));
      expect(audited()).toEqual([3, 3, 4, 2]);
    });

    it("shows a correction saved elsewhere on a finished run on coming back", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      answerAudioRun();
      renderRun(["flows_view"]);
      const lines = await screen.findByRole("list", { name: messages.flow_runs_transcript_lines });
      expect(within(lines).getByText("Tack.")).toBeTruthy();

      // Another reviewer corrects a line; the run itself does not move.
      state.routes[CORRECTIONS] = () => ({
        body: [
          {
            flow_run_id: "run-1",
            step_id: "step-1",
            created_at: "2026-10-21T09:00:00Z",
            updated_at: "2026-10-21T09:00:00Z",
            edited_by_principal_type: "user",
            schema_version: 3,
            segments_hash: "hash-1",
            stale: false,
            revision: 1,
            occurrences: [
              {
                segment_index: 1,
                char_start: 0,
                char_end: 4,
                original: "Tack",
                corrected: "Tackar"
              }
            ],
            speaker_edits: [],
            speaker_names: {}
          }
        ]
      });
      await comeBack();
      expect(await within(lines).findByText(/Tackar/)).toBeTruthy();
      expect(calls(STEPS)).toHaveLength(1);
    });

    it("plays the audio from a line or a word and marks the line playing", async () => {
      answerAudioRun();
      state.routes["POST /api/v1/flows/{id}/runs/{run_id}/input-files/{file_id}/signed-url/"] =
        () => ({
          body: {
            url: "http://backend:8000/api/v1/files/audio-1/download/?token=t0k3n",
            expires_at: "2026-10-21T10:00:00Z"
          }
        });
      state.routes["GET /api/v1/flows/{id}/runs/{run_id}/steps/{step_id}/transcript-words/"] =
        () => ({
          body: {
            alignment: "provider_words",
            created_at: "2026-10-21T09:00:00Z",
            flow_run_id: "run-1",
            step_id: "step-1",
            segments_hash: "hash-1",
            stale: false,
            segments: [
              {
                segment_index: 1,
                words: [{ word: "Tack.", start: 65.5, end: 66, probability: 0.9 }]
              }
            ]
          }
        });
      const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
      const { container } = renderRun(["flows_view"]);

      const lines = await screen.findByRole("list", { name: messages.flow_runs_transcript_lines });
      fireEvent.click(within(lines).getByRole("button", { name: /^Spela från 1:05/ }));
      const audio = await screen.findByLabelText<HTMLAudioElement>(
        messages.flow_transcript_audio_label
      );
      expect(audio.getAttribute("src")).toBe(
        "/api/eneo/api/v1/files/audio-1/download/?token=t0k3n"
      );
      fireEvent.loadedMetadata(audio);
      expect(audio.currentTime).toBe(65);
      expect(play).toHaveBeenCalled();

      Object.defineProperty(audio, "currentTime", {
        configurable: true,
        writable: true,
        value: 65.7
      });
      fireEvent.timeUpdate(audio);
      const playing = within(lines).getByRole("button", { name: /^Spela från 1:05/ });
      await waitFor(() => expect(playing.getAttribute("aria-current")).toBe("time"));
      expect(
        within(lines)
          .getByRole("button", { name: /^Spela från 0:00/ })
          .getAttribute("aria-current")
      ).toBeNull();
      // The word playing is marked for the eye only, once the word timings came.
      await waitFor(() => {
        fireEvent.timeUpdate(audio);
        expect(within(playing.closest("li")!).getByText("Tack.").className).toContain(
          "bg-ax-accent-muted"
        );
      });
      expect(container.querySelector("[aria-live] [data-word]")).toBeNull();
      await expectNoAxeViolations(container);
      play.mockRestore();
    });

    it("corrects a line's text, shows it corrected and reverts the correction", async () => {
      answerAudioRun();
      let revision = 0;
      state.routes[EDIT] = (init: { body: Record<string, unknown> }) => {
        revision += 1;
        return {
          body: {
            flow_run_id: "run-1",
            step_id: "step-1",
            created_at: "2026-10-21T09:00:00Z",
            updated_at: "2026-10-21T09:00:00Z",
            edited_by_principal_type: "user",
            schema_version: 3,
            segments_hash: "hash-1",
            stale: false,
            revision,
            occurrences: init.body.occurrences,
            speaker_edits: init.body.speaker_edits,
            speaker_names: init.body.speaker_names ?? {}
          }
        };
      };
      const { container } = renderRun(["flows_view", "flows_manage"]);
      const lines = await screen.findByRole("list", { name: messages.flow_runs_transcript_lines });

      fireEvent.click(within(lines).getByRole("button", { name: "Rätta raden 1:05" }));
      const field = within(lines).getByLabelText("Texten på raden 1:05");
      expect(document.activeElement).toBe(field);
      await expectNoAxeViolations(container);
      fireEvent.change(field, { target: { value: "Tack så mycket." } });
      fireEvent.click(
        within(lines).getByRole("button", { name: messages.flow_transcript_line_save })
      );

      await waitFor(() =>
        expect(state.announce).toHaveBeenCalledWith(messages.flow_transcript_line_saved)
      );
      expect(calls(EDIT)[0]?.init.body).toEqual({
        expected_revision: null,
        segments_hash: "hash-1",
        schema_version: 3,
        occurrences: [
          { segment_index: 1, char_start: 4, char_end: 5, original: ".", corrected: " så mycket." }
        ],
        speaker_edits: [],
        speaker_names: {}
      });
      expect(await within(lines).findByText(/Tack så mycket\./)).toBeTruthy();
      expect(within(lines).getByText(messages.flow_transcript_line_corrected)).toBeTruthy();
      // Focus goes back to the line's edit button.
      expect(document.activeElement).toBe(
        within(lines).getByRole("button", { name: "Rätta raden 1:05" })
      );

      fireEvent.click(within(lines).getByRole("button", { name: "Rätta raden 1:05" }));
      expect(within(lines).getByText("Ursprunglig text: Tack.")).toBeTruthy();
      fireEvent.click(
        within(lines).getByRole("button", { name: messages.flow_transcript_line_revert })
      );
      await waitFor(() =>
        expect(state.announce).toHaveBeenCalledWith(messages.flow_transcript_line_reverted)
      );
      expect(calls(EDIT)[1]?.init.body).toMatchObject({ expected_revision: 1, occurrences: [] });
      await waitFor(() =>
        expect(within(lines).queryByText(messages.flow_transcript_line_corrected)).toBeNull()
      );
    });

    it("gives a line, or a marked part of it, to another speaker", async () => {
      answerAudioRun();
      let revision = 0;
      state.routes[EDIT] = (init: { body: Record<string, unknown> }) => {
        revision += 1;
        return {
          body: {
            flow_run_id: "run-1",
            step_id: "step-1",
            created_at: "2026-10-21T09:00:00Z",
            updated_at: "2026-10-21T09:00:00Z",
            edited_by_principal_type: "user",
            schema_version: 3,
            segments_hash: "hash-1",
            stale: false,
            revision,
            occurrences: init.body.occurrences,
            speaker_edits: init.body.speaker_edits,
            speaker_names: init.body.speaker_names ?? {}
          }
        };
      };
      const { container } = renderRun(["flows_view", "flows_manage"]);
      const lines = await screen.findByRole("list", { name: messages.flow_runs_transcript_lines });

      // The whole line, unsure.
      fireEvent.click(within(lines).getByRole("button", { name: "Rätta raden 1:05" }));
      await expectNoAxeViolations(container);
      fireEvent.click(within(lines).getByLabelText(messages.flow_transcript_speaker_unsure));
      fireEvent.click(
        within(lines).getByRole("button", { name: messages.flow_transcript_speaker_apply })
      );
      await waitFor(() =>
        expect(state.announce).toHaveBeenCalledWith(messages.flow_transcript_speaker_saved)
      );
      expect(calls(EDIT)[0]?.init.body).toMatchObject({
        speaker_edits: [
          {
            segment_index: 1,
            char_start: null,
            char_end: null,
            original: null,
            original_speaker: "SPEAKER_01",
            speaker: "SPEAKER_00",
            decision: "unresolved"
          }
        ]
      });
      expect(
        await within(lines).findByText(messages.flow_transcript_speaker_unresolved)
      ).toBeTruthy();

      // The marked part of a line.
      fireEvent.click(within(lines).getByRole("button", { name: "Rätta raden 0:00" }));
      const field = within(lines).getByLabelText<HTMLTextAreaElement>("Texten på raden 0:00");
      field.setSelectionRange(0, 4);
      fireEvent.click(
        within(lines).getByRole("radio", { name: messages.flow_transcript_speaker_scope_selection })
      );
      fireEvent.click(
        within(lines).getByRole("button", { name: messages.flow_transcript_speaker_apply })
      );
      await waitFor(() => expect(calls(EDIT)).toHaveLength(2));
      expect(calls(EDIT)[1]?.init.body).toMatchObject({
        expected_revision: 1,
        speaker_edits: [
          {
            segment_index: 0,
            char_start: 0,
            char_end: 4,
            original: "Välk",
            original_speaker: "SPEAKER_00",
            speaker: "SPEAKER_01",
            decision: "confirmed"
          },
          { segment_index: 1, speaker: "SPEAKER_00", decision: "unresolved" }
        ]
      });
      expect(await within(lines).findByText("Välk")).toBeTruthy();
      expect(within(lines).getByText("omna.")).toBeTruthy();
    });

    it("shows the corrections' history and starts a run from the reviewed transcript", async () => {
      answerAudioRun();
      const saved = {
        flow_run_id: "run-1",
        step_id: "step-1",
        created_at: "2026-10-21T09:00:00Z",
        updated_at: "2026-10-21T09:00:00Z",
        edited_by_principal_type: "user",
        schema_version: 3,
        segments_hash: "hash-1",
        stale: false,
        revision: 2,
        occurrences: [
          { segment_index: 1, char_start: 0, char_end: 4, original: "Tack", corrected: "Tackar" }
        ],
        speaker_edits: [],
        speaker_names: { SPEAKER_00: "Anna" }
      };
      state.routes[CORRECTIONS] = () => ({ body: [saved] });
      state.routes[
        "GET /api/v1/flows/{id}/runs/{run_id}/transcript-corrections/{step_id}/revisions"
      ] = () => ({
        body: {
          baseline: {
            revision: 0,
            occurrences_json: [],
            speaker_edits_json: [],
            speaker_names: {}
          },
          truncated: false,
          next_after_revision: null,
          items: [
            {
              id: "rev-2",
              correction_set_id: "set-1",
              created_at: "2026-10-21T09:00:00Z",
              edited_by_principal_type: "user",
              edited_by_user_id: "user-1",
              edited_by_service_id: null,
              flow_id: "flow-1",
              flow_run_id: "run-1",
              step_id: "step-1",
              tenant_id: "tenant-1",
              revision: 2,
              segments_hash: "hash-1",
              occurrences_json: [{}],
              speaker_edits_json: [],
              speaker_names: { SPEAKER_00: "Anna" }
            }
          ]
        }
      });
      const REGENERATE =
        "POST /api/v1/flows/{id}/runs/{run_id}/steps/{step_id}/transcript-regenerations/";
      state.routes[REGENERATE] = () => ({
        status: 201,
        body: {
          run: { ...makeRunSummary({ id: "run-2", status: "queued" }) },
          created: true,
          source_run_id: "run-1",
          correction_revision: 2,
          first_regenerated_step_id: "step-2"
        }
      });
      const { container } = renderRun(["flows_view", "flows_manage"]);

      fireEvent.click(
        await screen.findByRole("button", { name: messages.flow_transcript_history_heading })
      );
      const history = await screen.findByRole("list", {
        name: messages.flow_transcript_history_heading
      });
      expect(within(history).getByText(/Version 2/)).toBeTruthy();
      expect(within(history).getByText(/· du$/)).toBeTruthy();
      expect(within(history).getByText("1 texträttning, 0 talarbyten, 1 namn")).toBeTruthy();
      await expectNoAxeViolations(container);

      fireEvent.click(screen.getByRole("button", { name: messages.flow_transcript_regenerate }));
      expect(await screen.findByText(messages.flow_transcript_regenerate_started)).toBeTruthy();
      const call = calls(REGENERATE)[0];
      expect(call?.init.body).toEqual({
        expected_run_revision: 3,
        expected_correction_revision: 2,
        segments_hash: "hash-1"
      });
      expect(
        (call?.init as { params?: { header?: Record<string, string> } }).params?.header?.[
          "Idempotency-Key"
        ]
      ).toBeTruthy();
      expect(
        screen
          .getByRole("link", { name: messages.flow_transcript_regenerate_open })
          .getAttribute("href")
      ).toBe("/spaces/space-1/flows/flow-1/runs/run-2");
    });

    it("shows a correction saved since the history was open when it opens again", async () => {
      answerAudioRun();
      const REVISIONS =
        "GET /api/v1/flows/{id}/runs/{run_id}/transcript-corrections/{step_id}/revisions";
      const set = (revision: number, occurrences: unknown) => ({
        flow_run_id: "run-1",
        step_id: "step-1",
        created_at: "2026-10-21T09:00:00Z",
        updated_at: "2026-10-21T09:00:00Z",
        edited_by_principal_type: "user",
        schema_version: 3,
        segments_hash: "hash-1",
        stale: false,
        revision,
        occurrences,
        speaker_edits: [],
        speaker_names: {}
      });
      const version = (revision: number) => ({
        id: `rev-${revision}`,
        correction_set_id: "set-1",
        created_at: "2026-10-21T09:00:00Z",
        edited_by_principal_type: "user",
        edited_by_user_id: "user-1",
        edited_by_service_id: null,
        flow_id: "flow-1",
        flow_run_id: "run-1",
        step_id: "step-1",
        tenant_id: "tenant-1",
        revision,
        segments_hash: "hash-1",
        occurrences_json: [],
        speaker_edits_json: [],
        speaker_names: {}
      });
      const versions = [version(1)];
      state.routes[CORRECTIONS] = () => ({ body: [set(1, [])] });
      state.routes[REVISIONS] = () => ({
        body: {
          baseline: {
            revision: 0,
            occurrences_json: [],
            speaker_edits_json: [],
            speaker_names: {}
          },
          truncated: false,
          next_after_revision: null,
          items: [...versions]
        }
      });
      state.routes[EDIT] = (init: { body: Record<string, unknown> }) => {
        versions.push(version(2));
        return { body: set(2, init.body.occurrences) };
      };
      renderRun(["flows_view", "flows_manage"]);
      const toggle = await screen.findByRole("button", {
        name: messages.flow_transcript_history_heading
      });
      const history = () =>
        screen.findByRole("list", { name: messages.flow_transcript_history_heading });

      fireEvent.click(toggle);
      expect(within(await history()).getByText(/Version 1/)).toBeTruthy();
      fireEvent.click(toggle);

      const lines = screen.getByRole("list", { name: messages.flow_runs_transcript_lines });
      fireEvent.click(within(lines).getByRole("button", { name: "Rätta raden 1:05" }));
      fireEvent.change(within(lines).getByLabelText("Texten på raden 1:05"), {
        target: { value: "Tack så mycket." }
      });
      fireEvent.click(
        within(lines).getByRole("button", { name: messages.flow_transcript_line_save })
      );
      await waitFor(() =>
        expect(state.announce).toHaveBeenCalledWith(messages.flow_transcript_line_saved)
      );

      fireEvent.click(toggle);
      expect(await within(await history()).findByText(/Version 2/)).toBeTruthy();
      expect(calls(REVISIONS)).toHaveLength(2);
    });

    it("marks where more than one voice spoke and lets the reviewer decide the speaker", async () => {
      answerAudioRun();
      const source = state.routes[SOURCE]!({} as never).body as Record<string, unknown>;
      const segments = source.segments as Record<string, unknown>[];
      state.routes[SOURCE] = () => ({
        body: {
          ...source,
          speaker_review: {
            files: [
              {
                file_index: 0,
                overlap_detection: "available",
                overlaps: [{ id: "f:o1", start: 64, end: 67, detected_speaker_count: 2 }]
              }
            ]
          },
          segments: [
            segments[0],
            { ...segments[1], overlap_ids: ["f:o1"], speaker_attribution: "provisional" }
          ]
        }
      });
      let revision = 0;
      state.routes[EDIT] = (init: { body: Record<string, unknown> }) => {
        revision += 1;
        return {
          body: {
            flow_run_id: "run-1",
            step_id: "step-1",
            created_at: "2026-10-21T09:00:00Z",
            updated_at: "2026-10-21T09:00:00Z",
            edited_by_principal_type: "user",
            schema_version: 3,
            segments_hash: "hash-1",
            stale: false,
            revision,
            occurrences: init.body.occurrences,
            speaker_edits: init.body.speaker_edits,
            speaker_names: init.body.speaker_names ?? {}
          }
        };
      };
      const { container } = renderRun(["flows_view", "flows_manage"]);

      expect(
        await screen.findByText("Ett ställe med överlappande tal behöver kontrolleras")
      ).toBeTruthy();
      const places = screen.getByRole("list", { name: messages.flow_transcript_overlap_list });
      expect(within(places).getByText("2 röster")).toBeTruthy();
      const lines = screen.getByRole("list", { name: messages.flow_runs_transcript_lines });
      expect(within(lines).getByText(messages.flow_transcript_overlap_line)).toBeTruthy();
      expect(within(lines).getByText(messages.flow_transcript_speaker_unresolved)).toBeTruthy();
      await expectNoAxeViolations(container);

      fireEvent.click(within(places).getByRole("button", { name: "Gå till 1:04–1:07" }));
      expect(document.activeElement).toBe(
        within(lines).getByRole("button", { name: /^Spela från 1:05/ })
      );

      fireEvent.click(within(lines).getByRole("button", { name: "Rätta raden 1:05" }));
      fireEvent.click(within(lines).getByRole("button", { name: "Behåll SPEAKER_01 som talare" }));
      await waitFor(() =>
        expect(state.announce).toHaveBeenCalledWith(messages.flow_transcript_speaker_confirmed)
      );
      expect(calls(EDIT)[0]?.init.body).toMatchObject({
        speaker_edits: [
          {
            segment_index: 1,
            char_start: null,
            original_speaker: "SPEAKER_01",
            speaker: "SPEAKER_01",
            decision: "confirmed"
          }
        ]
      });
      expect(await screen.findByText(messages.flow_transcript_overlap_done)).toBeTruthy();
      expect(within(lines).queryByText(messages.flow_transcript_speaker_unresolved)).toBeNull();
    });

    it("corrects the transcript inside a review of it, before approving", async () => {
      answerAudioRun();
      const waiting = makeRunSummary({ status: "awaiting_review", finished_at: null });
      state.routes[STATUS] = () => ({ body: waiting });
      state.routes[DETAIL] = () => ({ body: makeRunDetail({ ...waiting, result: null }) });
      state.routes[REVIEW] = () => ({
        body: makeCheckpoint({
          step_id: "step-1",
          step_order: 1,
          step_label: "Transkribera",
          current_payload_json: { text: "Välkomna. Tack." },
          original_payload_json: { text: "Välkomna. Tack." }
        })
      });
      state.routes[EDIT] = (init: { body: Record<string, unknown> }) => ({
        body: {
          flow_run_id: "run-1",
          step_id: "step-1",
          created_at: "2026-10-21T09:00:00Z",
          updated_at: "2026-10-21T09:00:00Z",
          edited_by_principal_type: "user",
          schema_version: 3,
          segments_hash: "hash-1",
          stale: false,
          revision: 1,
          occurrences: init.body.occurrences,
          speaker_edits: init.body.speaker_edits,
          speaker_names: init.body.speaker_names ?? {}
        }
      });
      const { container } = renderRun(["flows_view", "flows_manage"]);

      const panel = await screen.findByRole("region", { name: "Granska steg 1: Transkribera" });
      const lines = await within(panel).findByRole("list", {
        name: messages.flow_runs_transcript_lines
      });
      // The transcript shows once, in the review.
      expect(
        screen.getAllByRole("list", { name: messages.flow_runs_transcript_lines })
      ).toHaveLength(1);
      await expectNoAxeViolations(container);

      fireEvent.click(within(lines).getByRole("button", { name: "Rätta raden 1:05" }));
      fireEvent.change(within(lines).getByLabelText("Texten på raden 1:05"), {
        target: { value: "Tackar." }
      });
      // A change not saved holds the approval, and focus goes to it.
      for (const name of [
        messages.flow_runs_review_approve,
        messages.flow_run_extras_review_approve_only
      ]) {
        fireEvent.click(within(panel).getByRole("button", { name }));
        expect(
          await within(panel).findByText(messages.flow_transcript_review_unsaved)
        ).toBeTruthy();
        expect(document.activeElement).toBe(within(lines).getByLabelText("Texten på raden 1:05"));
      }
      expect(state.announce).toHaveBeenCalledWith(messages.flow_transcript_review_unsaved);
      expect(state.stub.calls.filter((call) => call.method === "POST")).toHaveLength(0);
      fireEvent.click(
        within(lines).getByRole("button", { name: messages.flow_transcript_line_save })
      );
      await waitFor(() =>
        expect(state.announce).toHaveBeenCalledWith(messages.flow_transcript_line_saved)
      );
      // The correction is the review's draft, which saves itself a moment later.
      await waitFor(() => expect(calls(EDIT)).toHaveLength(1), { timeout: 3_000 });
      expect(calls(EDIT)[0]?.init.body).toMatchObject({
        occurrences: [
          { segment_index: 1, char_start: 4, char_end: 5, original: ".", corrected: "ar." }
        ]
      });
      // Saved: the approval is no longer held.
      await waitFor(() =>
        expect(within(panel).queryByText(messages.flow_transcript_review_unsaved)).toBeNull()
      );
      expect(
        within(panel).getByRole("button", { name: messages.flow_runs_review_approve })
      ).toBeTruthy();
    });

    it("lets only someone who may review name the speakers", async () => {
      answerAudioRun();
      renderRun(["flows_view", "flows_run"]);
      await screen.findByRole("list", { name: messages.flow_runs_transcript_lines });
      expect(screen.queryByLabelText("Namn för SPEAKER_00")).toBeNull();
    });

    it.each([
      [1, messages.flow_runs_transcript_omitted],
      [2, messages.flow_runs_transcript_unavailable]
    ])("says why an omitted transcript (reason %i) has no lines", async (reason, text) => {
      answerAudioRun();
      state.routes[SOURCE] = () => ({
        body: {
          status: "omitted",
          run_id: "run-1",
          step_id: "step-1",
          attempt_no: 1,
          reason,
          bounds: { segments_bytes: 0, detail_bytes: 0, words_bytes: 0, segments_count: 0 }
        }
      });
      renderRun();
      expect(await screen.findByText(text)).toBeTruthy();
      expect(screen.queryByRole("list", { name: messages.flow_runs_transcript_lines })).toBeNull();
    });
  });
});
