import { describe, expect, it } from "vitest";
import {
  flowRefFromArguments,
  flowRefFromOutcome,
  hasFlowRef,
  isFlowsCall,
  mergeFlowRefs
} from "./flow-tool-calls";

const flowsCall = (toolName: string, input?: unknown, extra: Record<string, unknown> = {}) => ({
  toolName,
  input,
  providerMetadata: { eneo: { server_name: "flows", is_internal: true, ...extra } }
});

describe("isFlowsCall", () => {
  it("recognises a call routed to Eneo's own flows server", () => {
    expect(isFlowsCall(flowsCall("create_flow"))).toBe(true);
  });

  it("reads the live stream's metadata too", () => {
    expect(
      isFlowsCall({
        toolName: "run_flow",
        callProviderMetadata: { eneo: { server_name: "flows", is_internal: true } }
      })
    ).toBe(true);
  });

  it("does not borrow the name for an external server called flows", () => {
    expect(isFlowsCall(flowsCall("create_flow", undefined, { is_internal: false }))).toBe(false);
    expect(isFlowsCall(flowsCall("create_flow", undefined, { is_internal: null }))).toBe(false);
  });

  it("ignores other internal servers", () => {
    expect(
      isFlowsCall({
        toolName: "search_knowledge",
        providerMetadata: { eneo: { server_name: "knowledge", is_internal: true } }
      })
    ).toBe(false);
  });
});

describe("flow references", () => {
  it("reads the top-level ids of a result", () => {
    expect(flowRefFromOutcome({ flow_id: "f1", run_id: "r1", steps: [] })).toEqual({
      flowId: "f1",
      runId: "r1"
    });
    expect(flowRefFromOutcome({ flow_id: "f1", run_id: null })).toEqual({
      flowId: "f1",
      runId: null
    });
  });

  it("treats a missing, empty or malformed result as no reference", () => {
    expect(flowRefFromOutcome(null)).toEqual({ flowId: null, runId: null });
    expect(flowRefFromOutcome("text")).toEqual({ flowId: null, runId: null });
    expect(flowRefFromOutcome({ flow_id: "", run_id: 7 })).toEqual({ flowId: null, runId: null });
    expect(hasFlowRef(flowRefFromOutcome({ flows: [] }))).toBe(false);
  });

  it("reads the ids a call names in its arguments", () => {
    expect(flowRefFromArguments({ flow_id: "f1", name: "Protokoll" })).toEqual({
      flowId: "f1",
      runId: null
    });
    expect(flowRefFromArguments({ run_id: "r1" })).toEqual({ flowId: null, runId: "r1" });
    expect(flowRefFromArguments(undefined)).toEqual({ flowId: null, runId: null });
    expect(flowRefFromArguments(["f1"])).toEqual({ flowId: null, runId: null });
  });

  it("lets a later reference complete an earlier one", () => {
    expect(mergeFlowRefs({ flowId: "f1", runId: null }, { flowId: null, runId: "r1" })).toEqual({
      flowId: "f1",
      runId: "r1"
    });
    expect(mergeFlowRefs({ flowId: "f1", runId: "r1" }, { flowId: "f2", runId: null })).toEqual({
      flowId: "f2",
      runId: "r1"
    });
  });
});
