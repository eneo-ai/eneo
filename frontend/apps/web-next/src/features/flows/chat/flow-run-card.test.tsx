// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { ToolCallRecord } from "@/features/chat/side-panel/message-tool-calls";
import { makeRunDetail, makeRunGraph, makeRunSummary } from "../runs/run-fixtures";
import type { RunDetail, RunSummary } from "../runs/runs-api";

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

import { FlowRunCard, flowRunCardFor, startedRunId } from "./flow-run-card";

const STATUS = "GET /api/v1/flows/{id}/runs/{run_id}/status/";
const GRAPH = "GET /api/v1/flows/{id}/graph/";
const DETAIL = "GET /api/v1/flows/{id}/runs/{run_id}/";

function answerRun(
  summary: RunSummary,
  steps: { order: number; label: string; status: string | null }[],
  detail: RunDetail = makeRunDetail(summary)
) {
  state.routes[STATUS] = () => ({ body: summary });
  state.routes[GRAPH] = () => ({ body: makeRunGraph(steps) });
  state.routes[DETAIL] = () => ({ body: detail });
}

function calls(route: string) {
  return state.stub.calls.filter((call) => `${call.method} ${call.path}` === route);
}

function renderCard() {
  return renderInApp(
    <FlowRunCard flowId="flow-1" flowName="Förslagstest A" runId="run-1" spaceRouteId="space-1" />
  );
}

function runFlowCall(overrides: Partial<ToolCallRecord> = {}): ToolCallRecord {
  return {
    toolCallId: "call-1",
    toolName: "run_flow",
    state: "output-available",
    input: {},
    serverName: "flows",
    title: null,
    purpose: null,
    isInternal: true,
    isBundled: false,
    appView: null,
    approved: true,
    resultStatus: "succeeded",
    generatedFileIds: [],
    structuredContent: { flow_id: "flow-1", run_id: "run-1" },
    part: {
      type: "dynamic-tool",
      toolName: "run_flow",
      toolCallId: "call-1",
      state: "output-available",
      input: {},
      output: {}
    },
    ...overrides
  };
}

beforeEach(() => {
  state.routes = {};
});

afterEach(() => {
  cleanup();
  state.stub.calls.length = 0;
  vi.clearAllMocks();
});

describe("startedRunId", () => {
  it("names the run a retry_run call started too", () => {
    expect(startedRunId(runFlowCall({ toolName: "retry_run" }))).toBe("run-1");
  });

  it("names the run a run_flow call of the flow chat started, and nothing else", () => {
    expect(startedRunId(runFlowCall())).toBe("run-1");
    // Another tool of the flows server, a run_flow of an external server
    // named "flows", and a call without the run's id give no card.
    expect(startedRunId(runFlowCall({ toolName: "read_run" }))).toBeNull();
    expect(startedRunId(runFlowCall({ isInternal: false }))).toBeNull();
    expect(startedRunId(runFlowCall({ structuredContent: null }))).toBeNull();
    expect(
      flowRunCardFor(runFlowCall({ toolName: "read_flow" }), { id: "flow-1", name: "A" }, "space-1")
    ).toBeNull();
  });
});

describe("FlowRunCard", () => {
  it("shows a run under way step by step, with the way to it and to cancel it", async () => {
    answerRun(makeRunSummary({ status: "running", finished_at: null }), [
      { order: 1, label: "Sammanfatta", status: "completed" },
      { order: 2, label: "Skriv svar", status: "running" }
    ]);
    renderCard();
    const card = await screen.findByRole("region", { name: "Körning av Förslagstest A" });
    expect(await within(card).findByText(messages.flow_runs_status_running)).toBeTruthy();
    expect(within(card).getByText("Steg 2 av 2")).toBeTruthy();
    expect(within(card).getByText("Steg 2: Skriv svar")).toBeTruthy();
    expect(within(card).getByText(messages.flow_runs_step_status_completed)).toBeTruthy();
    expect(
      (
        within(card).getByRole("link", { name: "Öppna körningen" }) as HTMLAnchorElement
      ).getAttribute("href")
    ).toBe("/spaces/space-1/flows/flow-1/runs/run-1");
    expect(within(card).getByRole("button", { name: messages.flow_runs_cancel })).toBeTruthy();
    // The audited detail is not read while the run moves.
    expect(calls(DETAIL)).toHaveLength(0);
  });

  it("shows a finished run's result, with a copy and the way to the whole run", async () => {
    answerRun(makeRunSummary(), [
      { order: 1, label: "Sammanfatta", status: "completed" },
      { order: 2, label: "Skriv svar", status: "completed" }
    ]);
    const { container } = renderCard();
    const card = await screen.findByRole("region", { name: "Körning av Förslagstest A" });
    expect(await within(card).findByText("Beslutet är fattat.")).toBeTruthy();
    expect(within(card).getByText(messages.flow_runs_status_completed)).toBeTruthy();
    expect(within(card).getByText(/Version 3 · 2 steg · .* · .*token/)).toBeTruthy();
    expect(within(card).getByRole("button", { name: messages.copy })).toBeTruthy();
    expect(within(card).getByRole("link", { name: "Visa hela körningen" })).toBeTruthy();
    expect(within(card).queryByRole("button", { name: messages.flow_runs_cancel })).toBeNull();
    await expectNoAxeViolations(container);
  });

  it("says why a run failed, naming the step", async () => {
    const summary = makeRunSummary({ status: "failed" });
    answerRun(
      summary,
      [
        { order: 1, label: "Sammanfatta", status: "completed" },
        { order: 2, label: "Skriv svar", status: "failed" }
      ],
      makeRunDetail({
        ...summary,
        result: null,
        error: {
          code: "flow_step_timeout",
          message: "Step timed out.",
          retryable: true,
          step_order: 2,
          user_action: null,
          consumer_action: null,
          details: { phase: "provider_request" }
        } as RunDetail["error"]
      })
    );
    renderCard();
    const card = await screen.findByRole("region", { name: "Körning av Förslagstest A" });
    expect(await within(card).findByText(messages.flow_runs_failed_title)).toBeTruthy();
    expect(within(card).getByText(messages.flow_runs_status_failed)).toBeTruthy();
    await waitFor(() => expect(within(card).getByText(/Skriv svar/)).toBeTruthy());
    expect(within(card).queryByRole("button", { name: messages.copy })).toBeNull();
  });

  it("offers to explain a failure and to improve from a run, as prepared requests", async () => {
    const summary = makeRunSummary({ status: "failed" });
    answerRun(
      summary,
      [{ order: 1, label: "Skriv svar", status: "failed" }],
      makeRunDetail({
        ...summary,
        result: null,
        error: {
          code: "flow_step_timeout",
          message: "Step timed out.",
          retryable: true,
          step_order: 1,
          user_action: null,
          consumer_action: null,
          details: {}
        } as RunDetail["error"]
      })
    );
    const onAskChat = vi.fn();
    renderInApp(
      <FlowRunCard
        flowId="flow-1"
        flowName="Förslagstest A"
        runId="run-1"
        spaceRouteId="space-1"
        onAskChat={onAskChat}
      />
    );
    const card = await screen.findByRole("region", { name: "Körning av Förslagstest A" });
    fireEvent.click(await within(card).findByRole("button", { name: "Försök igen" }));
    expect(onAskChat).toHaveBeenLastCalledWith(expect.stringContaining("Starta om den"));
    fireEvent.click(within(card).getByRole("button", { name: "Förklara felet" }));
    expect(onAskChat).toHaveBeenLastCalledWith(expect.stringContaining("run-1"));
    expect(onAskChat).toHaveBeenLastCalledWith(expect.stringContaining("Förklara varför"));
    fireEvent.click(within(card).getByRole("button", { name: "Förbättra utifrån körningen" }));
    expect(onAskChat).toHaveBeenLastCalledWith(expect.stringContaining("Förbättra flödet"));
    expect(onAskChat).toHaveBeenCalledTimes(3);
  });

  it("offers no explanation for a run that completed, and nothing without a chat to ask", async () => {
    answerRun(makeRunSummary(), [{ order: 1, label: "Sammanfatta", status: "completed" }]);
    const onAskChat = vi.fn();
    renderInApp(
      <FlowRunCard
        flowId="flow-1"
        flowName="Förslagstest A"
        runId="run-1"
        spaceRouteId="space-1"
        onAskChat={onAskChat}
      />
    );
    const card = await screen.findByRole("region", { name: "Körning av Förslagstest A" });
    expect(
      await within(card).findByRole("button", { name: "Förbättra utifrån körningen" })
    ).toBeTruthy();
    expect(within(card).queryByRole("button", { name: "Förklara felet" })).toBeNull();
    cleanup();
    answerRun(makeRunSummary(), [{ order: 1, label: "Sammanfatta", status: "completed" }]);
    renderCard();
    const plain = await screen.findByRole("region", { name: "Körning av Förslagstest A" });
    await within(plain).findByText("Beslutet är fattat.");
    expect(within(plain).queryByRole("button", { name: "Förbättra utifrån körningen" })).toBeNull();
  });
});
