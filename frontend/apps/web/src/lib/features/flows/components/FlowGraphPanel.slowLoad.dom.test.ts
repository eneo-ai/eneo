import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/svelte";
import { afterEach, it, expect, vi } from "vitest";
import type { Flow } from "@eneo/eneo-js";
import Panel from "./FlowGraphPanel.svelte";

/**
 * Its own file because the import has to still be in flight while the test
 * watches, and a mocked module is resolved once per registry -- so the factory
 * that holds it can only serve one test. `vi.resetModules()` is not the way
 * round that: it hands a re-imported component a second Svelte runtime and
 * orphans its effects.
 */
const load = vi.hoisted(() => ({
  starts: 0,
  release: undefined as undefined | (() => void)
}));

vi.mock("./FlowGraph.svelte", async () => {
  load.starts += 1;
  await new Promise<void>((resolve) => {
    load.release = resolve;
  });
  const stub = await import("./FlowGraphStub.fixture.svelte");
  return { default: stub.default };
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

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

/**
 * The panel used to race this download against a five second timer, which is
 * what produced "Kunde inte ladda flödesvyn" on a cold cache. A download still
 * in flight is not a failure however long it takes, and when it lands the
 * graph appears.
 */
it("waits for a slow module rather than giving up on a timer", async () => {
  vi.useFakeTimers();
  render(Panel, { props: { flow, activeStepId: null } });
  await fireEvent.click(screen.getByRole("button", { name: /Flödesvy/ }));
  await waitFor(() => expect(load.starts).toBe(1));

  await vi.advanceTimersByTimeAsync(30_000);

  expect(screen.queryByText("Kunde inte ladda flödesvyn.")).toBeNull();
  expect(screen.getByText("Laddar flödesvy…")).toBeTruthy();
  expect(screen.queryByTestId("flow-graph-stub")).toBeNull();

  // Resolving the module and flushing the effect it feeds takes more turns
  // than a zero-length tick, and the waiting is what the fake clock was for.
  vi.useRealTimers();
  load.release?.();

  expect(await screen.findByTestId("flow-graph-stub")).toBeTruthy();
  expect(screen.queryByText("Laddar flödesvy…")).toBeNull();
});
