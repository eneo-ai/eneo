import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import type { Eneo, FlowGraph, FlowRunStep } from "@eneo/eneo-js";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import FlowRunProgressPanel from "./FlowRunProgressPanel.svelte";

function graphWith(status: string): FlowGraph {
  return {
    nodes: [{ id: "step-1", label: "Summarize", type: "llm", step_order: 1, run_status: status }],
    edges: []
  };
}

function stepsWith(status: FlowRunStep["status"]): FlowRunStep[] {
  return [
    {
      flow_run_id: "run-1",
      flow_id: "flow-1",
      tenant_id: "tenant-1",
      step_id: "step-1",
      step_order: 1,
      status,
      error_message: null,
      created_at: "2026-08-25T09:00:00Z",
      updated_at: "2026-08-25T09:00:01Z"
    }
  ];
}

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (e: unknown) => void;
};
function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function makeEneo(graphResponses: Array<Deferred<FlowGraph>>, steps: FlowRunStep[]) {
  let graphCall = 0;
  const graph = vi.fn(() => graphResponses[graphCall++].promise);
  const stepsFn = vi.fn(async () => steps);
  const eneo = { flows: { graph, runs: { steps: stepsFn } } } as unknown as Eneo;
  return { eneo, graph, steps: stepsFn };
}

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  // jsdom has no layout; the focused step's scroll is a no-op here.
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("FlowRunProgressPanel", () => {
  it("never lets an older background read roll back a fresher status", async () => {
    const initial = deferred<FlowGraph>();
    const slowPoll = deferred<FlowGraph>();
    const manual = deferred<FlowGraph>();
    const { eneo } = makeEneo([initial, slowPoll, manual], stepsWith("running"));
    const { rerender } = render(FlowRunProgressPanel, {
      props: { runId: "run-1", flowId: "flow-1", eneo, refreshTick: 0 }
    });
    initial.resolve(graphWith("running"));
    const panel = () => document.getElementById("flow-run-progress-step-1")!;
    await waitFor(() => expect(panel().textContent).toContain(m.flow_run_status_running()));

    // A poll starts and stalls; the user presses "Uppdatera nu" meanwhile.
    await rerender({ runId: "run-1", flowId: "flow-1", eneo, refreshTick: 1 });
    await fireEvent.click(screen.getByRole("button", { name: m.flow_run_progress_refresh() }));
    manual.resolve(graphWith("completed"));
    await waitFor(() => expect(panel().textContent).toContain(m.flow_run_status_completed()));

    // The stale poll answer arrives last and is ignored.
    slowPoll.resolve(graphWith("running"));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(panel().textContent).toContain(m.flow_run_status_completed());
    expect(panel().textContent).not.toContain(m.flow_run_status_running());
  });

  it("says when a background refresh failed and clears it once one succeeds", async () => {
    const initial = deferred<FlowGraph>();
    const failing = deferred<FlowGraph>();
    const recovering = deferred<FlowGraph>();
    const { eneo } = makeEneo([initial, failing, recovering], stepsWith("running"));
    const { rerender } = render(FlowRunProgressPanel, {
      props: { runId: "run-1", flowId: "flow-1", eneo, refreshTick: 0 }
    });
    initial.resolve(graphWith("running"));
    const panel = () => document.getElementById("flow-run-progress-step-1")!;
    await waitFor(() => expect(panel().textContent).toContain(m.flow_run_status_running()));

    await rerender({ runId: "run-1", flowId: "flow-1", eneo, refreshTick: 1 });
    failing.reject(new Error("gateway timeout"));
    await waitFor(() =>
      expect(screen.getByText(m.flow_run_progress_refresh_failed())).toBeTruthy()
    );
    // The last good snapshot stays on screen.
    expect(panel().textContent).toContain(m.flow_run_status_running());

    await rerender({ runId: "run-1", flowId: "flow-1", eneo, refreshTick: 2 });
    recovering.resolve(graphWith("completed"));
    await waitFor(() => expect(panel().textContent).toContain(m.flow_run_status_completed()));
    expect(screen.queryByText(m.flow_run_progress_refresh_failed())).toBeNull();
  });
});
