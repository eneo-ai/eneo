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
import { makeRunDetail, makeRunGraph, makeRunStep, makeRunSummary } from "./run-fixtures";
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
});
