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

function stepsWith(status: FlowRunStep["status"], text?: string): FlowRunStep[] {
  return [
    {
      flow_run_id: "run-1",
      flow_id: "flow-1",
      tenant_id: "tenant-1",
      step_id: "step-1",
      step_order: 1,
      status,
      error_message: null,
      ...(text ? { output_payload_json: { text } } : {}),
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

/** Graph and step responses in call order; each is handed out once. */
function makeEneo(graphs: Array<Deferred<FlowGraph>>, steps: Array<Deferred<FlowRunStep[]>>) {
  let graphCall = 0;
  let stepCall = 0;
  const graph = vi.fn(() => graphs[graphCall++].promise);
  const stepsFn = vi.fn(() => steps[stepCall++].promise);
  return { flows: { graph, runs: { steps: stepsFn } } } as unknown as Eneo;
}

const props = (eneo: Eneo, refreshTick: number) => ({
  runId: "run-1",
  flowId: "flow-1",
  eneo,
  refreshTick
});
const panel = () => document.getElementById("flow-run-progress-step-1")!;
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  // jsdom has no layout; the focused step's scroll is a no-op here.
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function renderRunning(
  eneo: Eneo,
  initialGraph: Deferred<FlowGraph>,
  initialSteps: Deferred<FlowRunStep[]>
) {
  const rendered = render(FlowRunProgressPanel, { props: props(eneo, 0) });
  initialGraph.resolve(graphWith("running"));
  initialSteps.resolve(stepsWith("running"));
  await waitFor(() => expect(panel().textContent).toContain(m.flow_run_status_running()));
  return rendered;
}

describe("FlowRunProgressPanel", () => {
  it("never lets an older background read roll back a fresher status", async () => {
    const [g0, g1, g2] = [deferred<FlowGraph>(), deferred<FlowGraph>(), deferred<FlowGraph>()];
    const [s0, s1] = [deferred<FlowRunStep[]>(), deferred<FlowRunStep[]>()];
    const eneo = makeEneo([g0, g1, g2], [s0, s1]);
    const { rerender } = await renderRunning(eneo, g0, s0);

    // A poll starts and stalls; the user presses "Uppdatera nu" meanwhile.
    await rerender(props(eneo, 1));
    await fireEvent.click(screen.getByRole("button", { name: m.flow_run_progress_refresh() }));
    g2.resolve(graphWith("completed"));
    s1.resolve(stepsWith("completed", "Klart"));
    await waitFor(() => expect(panel().textContent).toContain(m.flow_run_status_completed()));

    // The stale poll answer arrives last and is ignored.
    g1.resolve(graphWith("running"));
    await flush();
    expect(panel().textContent).toContain(m.flow_run_status_completed());
    expect(panel().textContent).not.toContain(m.flow_run_status_running());
  });

  it("shows the output a manual refresh fetched even when a later poll applied first", async () => {
    const [g0, g1, g2] = [deferred<FlowGraph>(), deferred<FlowGraph>(), deferred<FlowGraph>()];
    const [s0, s1] = [deferred<FlowRunStep[]>(), deferred<FlowRunStep[]>()];
    const eneo = makeEneo([g0, g1, g2], [s0, s1]);
    const { rerender } = await renderRunning(eneo, g0, s0);

    // Manual refresh: its graph answers, its audited step list is slow.
    await fireEvent.click(screen.getByRole("button", { name: m.flow_run_progress_refresh() }));
    g1.resolve(graphWith("completed"));
    // A poll started after it applies first: completed, outputs not read yet.
    await rerender(props(eneo, 1));
    g2.resolve(graphWith("completed"));
    await waitFor(() => expect(panel().textContent).toContain(m.flow_run_progress_details_stale()));

    // The slow step list arrives with the output: it is the newest detail
    // read and must not be discarded because a status poll came later.
    s1.resolve(stepsWith("completed", "Klart"));
    await waitFor(() => expect(panel().textContent).toContain("Klart"));
    expect(panel().textContent).not.toContain(m.flow_run_progress_details_stale());
    expect(panel().textContent).toContain(m.flow_run_status_completed());
  });

  it("trusts the audited step list over an older graph inside one refresh", async () => {
    const [g0, g1] = [deferred<FlowGraph>(), deferred<FlowGraph>()];
    const [s0, s1] = [deferred<FlowRunStep[]>(), deferred<FlowRunStep[]>()];
    const eneo = makeEneo([g0, g1], [s0, s1]);
    await renderRunning(eneo, g0, s0);

    await fireEvent.click(screen.getByRole("button", { name: m.flow_run_progress_refresh() }));
    // The graph was observed before the step finished; the step list after.
    g1.resolve(graphWith("running"));
    s1.resolve(stepsWith("completed", "Klart"));
    await waitFor(() => expect(panel().textContent).toContain("Klart"));
    expect(panel().textContent).toContain(m.flow_run_status_completed());
    expect(panel().textContent).not.toContain(m.flow_run_progress_details_stale());
  });

  it("says when a background refresh failed and clears it once one succeeds", async () => {
    const [g0, g1, g2] = [deferred<FlowGraph>(), deferred<FlowGraph>(), deferred<FlowGraph>()];
    const [s0] = [deferred<FlowRunStep[]>()];
    const eneo = makeEneo([g0, g1, g2], [s0]);
    const { rerender } = await renderRunning(eneo, g0, s0);

    await rerender(props(eneo, 1));
    g1.reject(new Error("gateway timeout"));
    await waitFor(() =>
      expect(screen.getByText(m.flow_run_progress_refresh_failed())).toBeTruthy()
    );
    // The last good snapshot stays on screen.
    expect(panel().textContent).toContain(m.flow_run_status_running());

    await rerender(props(eneo, 2));
    g2.resolve(graphWith("completed"));
    await waitFor(() => expect(panel().textContent).toContain(m.flow_run_status_completed()));
    expect(screen.queryByText(m.flow_run_progress_refresh_failed())).toBeNull();
  });

  it("ignores a superseded poll's failure", async () => {
    const [g0, g1, g2] = [deferred<FlowGraph>(), deferred<FlowGraph>(), deferred<FlowGraph>()];
    const [s0, s1] = [deferred<FlowRunStep[]>(), deferred<FlowRunStep[]>()];
    const eneo = makeEneo([g0, g1, g2], [s0, s1]);
    const { rerender } = await renderRunning(eneo, g0, s0);

    // A poll stalls; a manual refresh started later succeeds.
    await rerender(props(eneo, 1));
    await fireEvent.click(screen.getByRole("button", { name: m.flow_run_progress_refresh() }));
    g2.resolve(graphWith("completed"));
    s1.resolve(stepsWith("completed", "Klart"));
    await waitFor(() => expect(panel().textContent).toContain("Klart"));

    g1.reject(new Error("gateway timeout"));
    await flush();
    expect(screen.queryByText(m.flow_run_progress_refresh_failed())).toBeNull();
  });
});
