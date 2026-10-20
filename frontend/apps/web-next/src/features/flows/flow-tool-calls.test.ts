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

const FLOW_ID = "3f5a9d2e-1c4b-4e8a-9b7d-2a6c8e0f1b3d";
const RUN_ID = "7c1e4b9a-2d3f-4a5b-8c6d-9e0f1a2b3c4d";

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
    expect(flowRefFromOutcome({ flow_id: FLOW_ID, run_id: RUN_ID, steps: [] })).toEqual({
      flowId: FLOW_ID,
      runId: RUN_ID
    });
    expect(flowRefFromOutcome({ flow_id: FLOW_ID, run_id: null })).toEqual({
      flowId: FLOW_ID,
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
    expect(flowRefFromArguments({ flow_id: FLOW_ID, name: "Protokoll" })).toEqual({
      flowId: FLOW_ID,
      runId: null
    });
    expect(flowRefFromArguments({ run_id: RUN_ID })).toEqual({ flowId: null, runId: RUN_ID });
    expect(flowRefFromArguments(undefined)).toEqual({ flowId: null, runId: null });
    expect(flowRefFromArguments([FLOW_ID])).toEqual({ flowId: null, runId: null });
  });

  it("lets a later reference complete an earlier one", () => {
    expect(
      mergeFlowRefs({ flowId: FLOW_ID, runId: null }, { flowId: null, runId: RUN_ID })
    ).toEqual({
      flowId: FLOW_ID,
      runId: RUN_ID
    });
    expect(
      mergeFlowRefs({ flowId: FLOW_ID, runId: RUN_ID }, { flowId: "f2", runId: null })
    ).toEqual({
      flowId: "f2",
      runId: RUN_ID
    });
  });
});

describe("ids", () => {
  it("ignores a cut-short id from streamed arguments", () => {
    expect(flowRefFromArguments({ flow_id: "08226886-e851-450d-9" })).toEqual({
      flowId: null,
      runId: null
    });
    expect(
      flowRefFromOutcome({ flow_id: "08226886-e851-450d-9b6d-bf5420b60223", run_id: null })
    ).toEqual({
      flowId: "08226886-e851-450d-9b6d-bf5420b60223",
      runId: null
    });
  });
});
