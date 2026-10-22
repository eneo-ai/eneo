// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
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

function calls(route: string) {
  return state.stub.calls.filter((call) => `${call.method} ${call.path}` === route);
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
    expect(screen.getByText("Startad av Anna Lind")).toBeTruthy();
    expect(screen.queryByRole("button", { name: messages.flow_runs_cancel })).toBeNull();
    await expectNoAxeViolations(container);
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
    fireEvent.click(within(dialog).getByRole("button", { name: messages.flow_runs_cancel }));

    await waitFor(() =>
      expect(state.announce).toHaveBeenCalledWith(messages.flow_runs_cancel_done)
    );
    expect(calls("POST /api/v1/flows/{id}/runs/{run_id}/cancel/")).toHaveLength(1);
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
            { segment_index: 0, start: 0, end: 3, speaker: "SPEAKER_00", text: "Välkomna." },
            { segment_index: 1, start: 65, end: 70, speaker: "SPEAKER_01", text: "Tack." }
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
      expect(within(lines).getByText("SPEAKER_01:")).toBeTruthy();
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

    it("lets only someone who may review name the speakers", async () => {
      answerAudioRun();
      renderRun(["flows_view", "flows_run"]);
      await screen.findByRole("list", { name: messages.flow_runs_transcript_lines });
      expect(screen.queryByLabelText("Namn för SPEAKER_00")).toBeNull();
    });
  });
});
