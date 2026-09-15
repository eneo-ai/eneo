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

  it("does not start a status poll while a detail read is in flight", async () => {
    const [g0, g1, g2] = [deferred<FlowGraph>(), deferred<FlowGraph>(), deferred<FlowGraph>()];
    const [s0, s1] = [deferred<FlowRunStep[]>(), deferred<FlowRunStep[]>()];
    const eneo = makeEneo([g0, g1, g2], [s0, s1]);
    const { rerender } = await renderRunning(eneo, g0, s0);
    const graph = eneo.flows.graph as unknown as { mock: { calls: unknown[] } };

    await fireEvent.click(screen.getByRole("button", { name: m.flow_run_progress_refresh() }));
    expect(graph.mock.calls).toHaveLength(2);
    // A poll tick during the refresh is skipped, not queued.
    await rerender(props(eneo, 1));
    await flush();
    expect(graph.mock.calls).toHaveLength(2);

    g1.resolve(graphWith("completed"));
    s1.resolve(stepsWith("completed", "Klart"));
    await waitFor(() => expect(panel().textContent).toContain("Klart"));

    // Polling resumes on the next tick.
    await rerender(props(eneo, 2));
    await waitFor(() => expect(graph.mock.calls).toHaveLength(3));
    g2.resolve(graphWith("completed"));
    await flush();
    expect(panel().textContent).toContain("Klart");
  });

  it("drops a poll that started before a refresh, whichever answer arrives first", async () => {
    for (const pollAnswersFirst of [true, false]) {
      cleanup();
      const [g0, g1, g2] = [deferred<FlowGraph>(), deferred<FlowGraph>(), deferred<FlowGraph>()];
      const [s0, s1] = [deferred<FlowRunStep[]>(), deferred<FlowRunStep[]>()];
      const eneo = makeEneo([g0, g1, g2], [s0, s1]);
      const { rerender } = await renderRunning(eneo, g0, s0);

      // The poll starts first and will say "running"; the refresh started
      // after it sees the step finish.
      await rerender(props(eneo, 1));
      await fireEvent.click(screen.getByRole("button", { name: m.flow_run_progress_refresh() }));
      if (pollAnswersFirst) {
        g1.resolve(graphWith("running"));
        await flush();
      }
      g2.resolve(graphWith("completed"));
      s1.resolve(stepsWith("completed", "Klart"));
      await waitFor(() => expect(panel().textContent).toContain("Klart"));
      if (!pollAnswersFirst) {
        g1.resolve(graphWith("running"));
        await flush();
      }

      expect(panel().textContent).toContain("Klart");
      expect(panel().textContent).toContain(m.flow_run_status_completed());
      expect(panel().textContent).not.toContain(m.flow_run_progress_details_stale());
      expect(panel().textContent).not.toContain(m.flow_run_status_running());
    }
  });

  it("ignores a superseded initial load's failure when a refresh already replaced it", async () => {
    const [g0, g1, g2] = [deferred<FlowGraph>(), deferred<FlowGraph>(), deferred<FlowGraph>()];
    const [s0, s1] = [deferred<FlowRunStep[]>(), deferred<FlowRunStep[]>()];
    const eneo = makeEneo([g0, g1, g2], [s0, s1]);
    const graph = eneo.flows.graph as unknown as { mock: { calls: unknown[] } };
    // Reopened with a cached snapshot: the panel shows it (and the refresh
    // button) while the initial read is still out.
    const { rerender } = render(FlowRunProgressPanel, {
      props: {
        ...props(eneo, 0),
        initialSnapshot: {
          steps: [{ stepOrder: 1, label: "Summarize", status: "running", resultFiles: [] }]
        }
      }
    });
    await waitFor(() => expect(panel().textContent).toContain(m.flow_run_status_running()));

    await fireEvent.click(screen.getByRole("button", { name: m.flow_run_progress_refresh() }));
    g1.resolve(graphWith("running"));
    s1.resolve(stepsWith("running", "Delvis"));
    await waitFor(() => expect(panel().textContent).toContain("Delvis"));

    // The stalled initial read no longer counts: the next tick polls and the
    // status moves on while that read is still out.
    await rerender(props(eneo, 1));
    await waitFor(() => expect(graph.mock.calls).toHaveLength(3));
    g2.resolve(graphWith("completed"));
    await waitFor(() => expect(panel().textContent).toContain(m.flow_run_status_completed()));

    g0.reject(new Error("gateway timeout"));
    s0.resolve(stepsWith("running"));
    await flush();
    expect(screen.queryByText(m.flow_run_progress_load_failed())).toBeNull();
    expect(panel().textContent).toContain(m.flow_run_status_completed());
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
