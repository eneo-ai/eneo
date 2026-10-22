// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { makeRunSummary } from "./run-fixtures";
import type { RunSummary } from "./runs-api";

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
vi.mock("@astryxdesign/core/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@astryxdesign/core/hooks")>()),
  useAnnounce: () => state.announce
}));

import { FlowRunsList } from "./runs-list";

const LIST = "GET /api/v1/flows/{id}/runs/";

function answerList(items: RunSummary[], hasMore = false) {
  state.routes[LIST] = () => ({ body: { count: items.length, items, has_more: hasMore } });
}

function listCalls() {
  return state.stub.calls.filter((call) => `${call.method} ${call.path}` === LIST);
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

describe("FlowRunsList", () => {
  it("lists the runs with status, start, who started them, duration and version", async () => {
    answerList([
      makeRunSummary({ id: "run-2", status: "failed" }),
      makeRunSummary({
        id: "run-1",
        principal_type: "service_key",
        started_by: {
          principal_type: "service_key",
          id: "service-1",
          display_name: "Ärendeintag",
          email: null
        },
        purpose: "test"
      }),
      makeRunSummary({ id: "run-0", principal_type: "service_key", started_by: null })
    ]);
    const { container } = renderInApp(<FlowRunsList flowId="flow-1" spaceRouteId="space-1" />);

    const table = await screen.findByRole("table", { name: messages.flow_runs_heading });
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(4);
    expect(within(rows[1]!).getByText(messages.flow_runs_status_failed)).toBeTruthy();
    expect(within(rows[1]!).getByText("1 min 5 s")).toBeTruthy();
    expect(within(rows[1]!).getByText("Version 3")).toBeTruthy();
    expect(within(rows[1]!).getByText("Anna Lind")).toBeTruthy();
    expect(within(rows[2]!).getByText("Ärendeintag")).toBeTruthy();
    // A backend that names no one still says what kind of principal it was.
    expect(within(rows[3]!).getByText(messages.flow_runs_started_by_service_key)).toBeTruthy();
    expect(within(rows[2]!).getByText(messages.flow_runs_purpose_test)).toBeTruthy();
    const link = within(rows[1]!).getByRole("link");
    expect(link.getAttribute("href")).toBe("/spaces/space-1/flows/flow-1/runs/run-2");
    await expectNoAxeViolations(container);
  });

  it("says when there are no runs yet", async () => {
    answerList([]);
    const { container } = renderInApp(<FlowRunsList flowId="flow-1" spaceRouteId="space-1" />);
    expect(await screen.findByText(messages.flow_runs_empty_title)).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("asks for the caller's own runs only when asked", async () => {
    answerList([makeRunSummary()]);
    renderInApp(<FlowRunsList flowId="flow-1" spaceRouteId="space-1" />);
    await screen.findByRole("table");
    expect(listCalls()[0]?.init.params?.query).toEqual({ limit: 25, offset: 0 });

    fireEvent.click(screen.getByRole("checkbox", { name: messages.flow_runs_only_mine }));
    await vi.waitFor(() =>
      expect(listCalls().at(-1)?.init.params?.query).toEqual({ limit: 25, offset: 0, mine: true })
    );
  });

  it("polls while a run moves, announces the change, then stops", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    answerList([makeRunSummary({ status: "running", finished_at: null, revision: 1 })]);
    renderInApp(<FlowRunsList flowId="flow-1" spaceRouteId="space-1" />);
    await screen.findByText(messages.flow_runs_status_running);
    expect(listCalls()).toHaveLength(1);

    answerList([makeRunSummary({ status: "completed", revision: 2 })]);
    await act(() => vi.advanceTimersByTimeAsync(2_100));
    await screen.findByText(messages.flow_runs_status_completed);
    expect(listCalls()).toHaveLength(2);
    expect(state.announce).toHaveBeenCalledWith(
      messages.flow_runs_status_changed.replace("{status}", messages.flow_runs_status_completed)
    );

    await act(() => vi.advanceTimersByTimeAsync(20_000));
    expect(listCalls()).toHaveLength(2);
  });

  it("does not poll a list where every run has ended", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    answerList([makeRunSummary({ status: "completed" })]);
    renderInApp(<FlowRunsList flowId="flow-1" spaceRouteId="space-1" />);
    await screen.findByText(messages.flow_runs_status_completed);
    await act(() => vi.advanceTimersByTimeAsync(20_000));
    expect(listCalls()).toHaveLength(1);
  });

  it("reads older runs a page at a time", async () => {
    answerList([makeRunSummary()], true);
    renderInApp(<FlowRunsList flowId="flow-1" spaceRouteId="space-1" />);
    fireEvent.click(await screen.findByRole("button", { name: messages.flow_runs_show_more }));
    await vi.waitFor(() =>
      expect(listCalls().at(-1)?.init.params?.query).toEqual({ limit: 25, offset: 25 })
    );
  });
});
