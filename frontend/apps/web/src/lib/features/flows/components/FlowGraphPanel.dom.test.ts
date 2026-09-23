import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, it, expect, vi } from "vitest";
import type { Flow } from "@eneo/eneo-js";
import Panel from "./FlowGraphPanel.svelte";

/**
 * The real graph needs @xyflow/svelte, dagre and a layout engine jsdom does
 * not have, so the module is the thing to stand in for. These two cases share
 * one resolved module deliberately: `vi.resetModules()` would hand a
 * re-imported component a second Svelte runtime and orphan its effects. The
 * pending-import case, which does need its own factory run, lives in
 * FlowGraphPanel.slowLoad.dom.test.ts.
 *
 * `starts` counts entries into the factory, which is the import itself rather
 * than a later read of what it returned. The failure is raised from the
 * property rather than the factory because a rejected dynamic import stays
 * rejected for the life of the module registry, which would leave a
 * recovering retry untestable.
 */
const load = vi.hoisted(() => ({ starts: 0, fail: false }));

vi.mock("./FlowGraph.svelte", async () => {
  load.starts += 1;
  const stub = await import("./FlowGraphStub.fixture.svelte");
  return {
    get default() {
      if (load.fail) throw new Error("chunk unavailable");
      return stub.default;
    }
  };
});

Element.prototype.animate ??= (() => ({
  cancel() {},
  finished: Promise.resolve(),
  onfinish: null
})) as never;

const flow = {
  id: "flow-1",
  name: "Genomförandeplan",
  steps: [{ id: "step-1", step_order: 1 }]
} as unknown as Flow;

const openPanel = () => fireEvent.click(screen.getByRole("button", { name: /Flödesvy/ }));

beforeEach(() => {
  load.fail = false;
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/**
 * The module carries @xyflow/svelte and dagre. Every flow page mounts this
 * panel collapsed, so fetching on mount made all of them pay for a graph
 * nobody had asked to see.
 */
it("does not fetch the graph module until someone opens the panel", async () => {
  render(Panel, { props: { flow, activeStepId: null } });

  await waitFor(() => expect(screen.getByText("Flödesvy")).toBeTruthy());
  expect(load.starts).toBe(0);

  await openPanel();

  await waitFor(() => expect(load.starts).toBe(1));
  expect(await screen.findByTestId("flow-graph-stub")).toBeTruthy();
});

/**
 * A genuine failure has to stay recoverable, and recovered means the graph is
 * on screen -- not merely that the error text went away, which happens the
 * instant the retry re-enters loading.
 */
it("recovers to a rendered graph when a failed load is retried", async () => {
  load.fail = true;
  render(Panel, { props: { flow, activeStepId: null } });
  await openPanel();

  await waitFor(() => expect(screen.getByText("Flödesvyn kunde inte laddas.")).toBeTruthy());
  expect(console.error).toHaveBeenCalled();

  load.fail = false;
  await fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));

  expect(await screen.findByTestId("flow-graph-stub")).toBeTruthy();
  expect(screen.queryByText("Flödesvyn kunde inte laddas.")).toBeNull();
  expect(screen.queryByText("Laddar flödesvy…")).toBeNull();
});
