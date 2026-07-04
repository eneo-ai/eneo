import { describe, it, expect, vi } from "vitest";
import type { FlowStep } from "@eneo/eneo-js";
import type { FlowEditor } from "$lib/features/flows/FlowEditor";
import { FlowStepMcpState } from "./FlowStepMcpState.svelte.ts";

function makeStep(overrides: Record<string, unknown>): FlowStep {
  return { id: "s", assistant_id: "a1", step_order: 1, ...overrides } as FlowStep;
}

function makeState(loadAssistant: (id: string) => Promise<unknown>): FlowStepMcpState {
  return new FlowStepMcpState({ flowEditor: { loadAssistant } as unknown as FlowEditor });
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("FlowStepMcpState.syncAssistants", () => {
  it("does nothing when the MCP section is hidden", () => {
    const load = vi.fn(async () => ({}));
    const state = makeState(load);
    state.syncAssistants({
      revision: 1,
      activeStep: makeStep({ assistant_id: "a1" }),
      steps: [makeStep({ assistant_id: "a1" })],
      activeAssistant: { id: "a1" },
      showMcpSection: false
    });
    expect(load).not.toHaveBeenCalled();
    expect(state.assistantsById.size).toBe(0);
  });

  it("stores the active assistant directly without loading it", () => {
    const load = vi.fn(async () => ({}));
    const state = makeState(load);
    const activeAssistant = { id: "a1", tag: "active" };
    state.syncAssistants({
      revision: 1,
      activeStep: makeStep({ assistant_id: "a1" }),
      steps: [makeStep({ assistant_id: "a1" })],
      activeAssistant,
      showMcpSection: true
    });
    expect(state.assistantsById.get("a1")).toBe(activeAssistant);
    expect(load).not.toHaveBeenCalled();
  });

  it("loads a non-active step assistant once and dedupes by revision", async () => {
    const load = vi.fn(async (id: string) => ({ id, loaded: true }));
    const state = makeState(load);
    const steps = [
      makeStep({ assistant_id: "a1" }),
      makeStep({ assistant_id: "a2", step_order: 2 })
    ];
    const call = (revision: number) =>
      state.syncAssistants({
        revision,
        activeStep: makeStep({ assistant_id: "a1" }),
        steps,
        activeAssistant: { id: "a1" },
        showMcpSection: true
      });

    call(1);
    await flush();
    expect(load).toHaveBeenCalledTimes(1);
    expect(load).toHaveBeenCalledWith("a2");
    expect(state.assistantsById.get("a2")).toEqual({ id: "a2", loaded: true });

    call(1);
    await flush();
    expect(load).toHaveBeenCalledTimes(1); // same revision -> no reload

    call(2);
    await flush();
    expect(load).toHaveBeenCalledTimes(2); // new revision -> reload
  });

  it("does not start a second load while one is in flight", async () => {
    let resolveLoad: (value: unknown) => void = () => {};
    const load = vi.fn(() => new Promise<unknown>((resolve) => (resolveLoad = resolve)));
    const state = makeState(load as unknown as (id: string) => Promise<unknown>);
    const args = {
      revision: 1,
      activeStep: null,
      steps: [makeStep({ assistant_id: "a2", step_order: 2 })],
      activeAssistant: null,
      showMcpSection: true
    };
    state.syncAssistants(args);
    state.syncAssistants(args);
    expect(load).toHaveBeenCalledTimes(1);
    resolveLoad({ id: "a2" });
    await flush();
    expect(state.assistantsById.get("a2")).toEqual({ id: "a2" });
  });
});

describe("FlowStepMcpState compatibility", () => {
  const base = {
    steps: [] as FlowStep[],
    availableServers: [],
    spaceSecurityClassification: null,
    reasonWhenIncompatible: "x"
  };

  it("returns an empty compatibility map with no active step or a hidden section", () => {
    const state = makeState(vi.fn(async () => ({})));
    expect(state.getCompatibilityById({ ...base, activeStep: null, showMcpSection: true })).toEqual(
      {}
    );
    expect(
      state.getCompatibilityById({ ...base, activeStep: makeStep({}), showMcpSection: false })
    ).toEqual({});
  });

  it("is not ready until every required-order assistant is loaded", () => {
    const state = makeState(vi.fn(async () => ({})));
    const step = makeStep({ step_order: 1, assistant_id: "a1" });
    expect(state.isCompatibilityReady({ activeStep: step, steps: [step] })).toBe(false);
    state.assistantsById.set("a1", { id: "a1" });
    expect(state.isCompatibilityReady({ activeStep: step, steps: [step] })).toBe(true);
  });

  it("is not ready when there is no active step", () => {
    const state = makeState(vi.fn(async () => ({})));
    expect(state.isCompatibilityReady({ activeStep: null, steps: [] })).toBe(false);
  });
});
