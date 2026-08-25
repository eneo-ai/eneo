import { createEneo, type Eneo, type Flow, type FlowRun } from "@eneo/eneo-js";

type FlowRunResultFileItem = NonNullable<FlowRun["result_files"]>[number];

/**
 * Canonical valid FlowRun test fixture carrying every field the generated
 * contract requires, so tests fail at compile time when the contract grows
 * instead of feeding components `undefined` through unknown-casts.
 */
export function makeFlowRun(overrides: Partial<FlowRun> = {}): FlowRun {
  const base: FlowRun = {
    id: "run-1",
    flow_id: "flow-1",
    tenant_id: "tenant-1",
    trace_id: "trace-1",
    revision: 1,
    dispatch_attempt_count: 1,
    status: "completed",
    created_at: "2026-08-25T09:00:00Z",
    updated_at: "2026-08-25T09:00:00Z",
    flow_version: 1,
    input_payload_json: { arende: "Bygglov Storgatan 5" }
  };
  return { ...base, ...overrides };
}

/** Canonical result-file fixture carrying the generated required fields. */
export function makeFlowRunResultFile(
  overrides: Partial<FlowRunResultFileItem> = {}
): FlowRunResultFileItem {
  const base: FlowRunResultFileItem = {
    flow_run_id: "run-1",
    flow_id: "flow-1",
    tenant_id: "tenant-1",
    step_result_id: "step-result-1",
    step_id: "step-1",
    step_order: 1,
    ordinal: 0,
    attempt_no: 1,
    file_id: "file-1",
    name: "resultat.pdf",
    mimetype: "application/pdf",
    file_type: "document",
    size: 1024,
    source: "generated_output",
    checksum: "checksum-1",
    availability: "available"
  };
  return { ...base, ...overrides };
}

// jsdom has no matchMedia; svelte/reactivity's MediaQuery (via the IsMobile
// owner) needs one at component construction. Tests choose the viewport via
// setTestViewportMobile; the default (false) renders the desktop tree.
let testViewportMobile = false;

export function setTestViewportMobile(mobile: boolean): void {
  testViewportMobile = mobile;
}

if (typeof window !== "undefined" && typeof window.matchMedia !== "function") {
  window.matchMedia = (query: string) =>
    ({
      // IsMobile queries max-width, so "matches" means mobile.
      get matches() {
        return query.includes("max-width") ? testViewportMobile : !testViewportMobile;
      },
      media: query,
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false
    }) as unknown as MediaQueryList;
}

type FlowRunListResult = Awaited<ReturnType<Eneo["flows"]["runs"]["list"]>>;

/** Minimal valid Flow for table harnesses. */
export function makeTestFlow(): Flow {
  const flow: Flow = {
    id: "flow-1",
    name: "Testflöde",
    tenant_id: "tenant-1",
    space_id: "space-1",
    step_count: 1,
    steps: [],
    run_history_retention: {
      source: "none",
      state: "off",
      effective_days: null,
      contributors: { organization_days: null, space_days: null, flow_days: null }
    }
  };
  return flow;
}

/**
 * The REAL generated client over a fake fetch transport: request routing and
 * response decoding stay the SDK's own, so fixtures cannot drift from the
 * generated contract (the body constant is typed against the list return).
 */
export function makeRunsListEneo(handler: (url: URL) => { items: FlowRun[]; has_more: boolean }) {
  const calls: Array<{ limit: number; offset: number }> = [];
  const evidenceCalls: string[] = [];
  const eneo: Eneo = createEneo({
    baseUrl: "http://backend.invalid",
    fetch: async (input: RequestInfo | URL) => {
      const url = new URL(String(input instanceof Request ? input.url : input));
      if (/\/evidence\/$/.test(url.pathname)) {
        evidenceCalls.push(url.pathname);
        // Typed against the generated evidence return so the fixture cannot
        // drift from the contract.
        type EvidenceBundle = Awaited<ReturnType<Eneo["flows"]["runs"]["evidence"]>>;
        // Every collection the panel iterates is present and typed; the two
        // remaining required sub-objects (debug_export, definition_integrity
        // and the definition snapshot) are deep server-composed structures
        // the empty-state render never reads — the single cast covers
        // exactly that elision.
        const evidenceCollections = {
          run: makeFlowRun({ id: "aaa" }),
          step_results: [],
          step_attempts: [],
          result_files: [],
          review_checkpoints: [],
          provider_calls: {
            count: 0,
            has_more: false,
            items: [],
            next_after_event_id: null,
            total_count: 0
          },
          webhook_deliveries: []
        } satisfies Partial<EvidenceBundle>;
        const evidenceBody = evidenceCollections as unknown as EvidenceBundle;
        return new Response(JSON.stringify(evidenceBody), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        });
      }
      if (!/\/runs\/$/.test(url.pathname)) {
        return new Response(JSON.stringify({}), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        });
      }
      const limit = Number(url.searchParams.get("limit") ?? "50");
      const offset = Number(url.searchParams.get("offset") ?? "0");
      calls.push({ limit, offset });
      const handled = handler(url);
      const body: FlowRunListResult = { count: handled.items.length, ...handled };
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    }
  });
  return { eneo, calls, evidenceCalls };
}
