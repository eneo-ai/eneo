// @vitest-environment jsdom
import { focusManager } from "@tanstack/react-query";
import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext } from "@/test/render";
import { makeFlow } from "../flow-fixtures";
import { runStepViews } from "./run-progress";
import { makeRunGraph, makeRunSummary } from "./run-fixtures";
import type { EvidenceAccess, RunEvidence } from "./runs-api";

const state = vi.hoisted(() => ({
  announce: vi.fn(),
  saveBlob: vi.fn(),
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
vi.mock("@/features/chat/side-panel/document-export", () => ({ saveBlob: state.saveBlob }));

import { RunTrace } from "./run-trace";

const EVIDENCE = "GET /api/v1/flows/{id}/runs/{run_id}/evidence/";
const CALLS = "GET /api/v1/flows/{id}/runs/{run_id}/provider-calls/";
const EXPORT = "GET /api/v1/flows/{id}/runs/{run_id}/evidence/export";

const steps = runStepViews(
  makeRunGraph([
    { order: 1, label: "Sammanfatta", status: "completed" },
    { order: 2, label: "Skriv svar", status: "completed" }
  ]),
  []
);

function call(ordinal: number) {
  return {
    event_id: `event-${ordinal}`,
    attempt_id: "attempt-2-1",
    attempt_no: 1,
    step_id: "step-2",
    step_order: 2,
    ordinal,
    call_kind: "completion",
    call_reason: ordinal === 1 ? "initial" : "tool_round",
    requested_model: "model-large",
    response_model: "model-large-2026",
    status: ordinal === 1 ? "completed" : "outcome_unknown",
    num_tokens_input: 1000,
    num_tokens_output: 200,
    requested_at: "2026-10-21T08:00:10Z",
    finished_at: "2026-10-21T08:00:20Z"
  };
}

function evidence(): RunEvidence {
  return {
    run: makeRunSummary(),
    debug_export: {
      schema_version: "eneo.flow.debug-export.v3",
      generated_at: "2026-10-21T08:02:00Z",
      run: { run_id: "run-1", flow_id: "flow-1", flow_version: 3, status: "completed" },
      security: { classification_field: "", content_included: false, redaction_applied: true },
      definition: {},
      steps: []
    },
    step_attempts: [
      {
        id: "attempt-2-1",
        step_order: 2,
        attempt_no: 1,
        status: "failed",
        error_code: "flow_provider_rate_limited",
        started_at: "2026-10-21T08:00:05Z",
        finished_at: "2026-10-21T08:00:09Z"
      },
      {
        id: "attempt-2-2",
        step_order: 2,
        attempt_no: 2,
        status: "completed",
        requested_model: "model-large",
        response_model: "model-large-2026",
        finish_reason: "stop",
        num_tokens_input: 1000,
        num_tokens_output: 200,
        started_at: "2026-10-21T08:00:10Z",
        finished_at: "2026-10-21T08:00:30Z"
      }
    ],
    provider_calls: {
      count: 1,
      items: [call(1)],
      has_more: true,
      next_after_event_id: "event-1",
      total_count: 2
    },
    knowledge_traces: [],
    step_results: [],
    result_files: [],
    review_checkpoints: [],
    webhook_deliveries: [],
    definition_snapshot: {},
    definition_integrity: {}
  } as unknown as RunEvidence;
}

const ALL_ALLOWED: EvidenceAccess = {
  can_read_evidence: true,
  can_export_redacted: true,
  can_export_raw: true,
  read_refusal_code: null,
  redacted_export_refusal_code: null,
  raw_export_refusal_code: null
};

function renderTrace(access: EvidenceAccess = ALL_ALLOWED) {
  return renderInApp(
    <RunTrace flow={makeFlow()} summary={makeRunSummary()} steps={steps} access={access} />,
    { appContext: testAppContext({ permissions: ["flows_view"] }) }
  );
}

function calls(route: string) {
  return state.stub.calls.filter((item) => `${item.method} ${item.path}` === route);
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

describe("RunTrace", () => {
  it("is not offered to a caller the core would not let read the evidence", () => {
    renderTrace({
      ...ALL_ALLOWED,
      can_read_evidence: false,
      read_refusal_code: "insufficient_tenant_permission"
    });
    expect(
      screen.queryByRole("heading", { name: messages.flow_run_extras_trace_heading })
    ).toBeNull();
  });

  it("reads the evidence only when asked, then shows attempts and calls", async () => {
    state.routes[EVIDENCE] = () => ({ body: evidence() });
    state.routes[CALLS] = () => ({
      body: {
        count: 1,
        items: [call(2)],
        has_more: false,
        next_after_event_id: null,
        total_count: 2
      }
    });
    const { container } = renderTrace();
    expect(calls(EVIDENCE)).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: messages.flow_run_extras_trace_show }));
    const attempts = await screen.findByRole("list", { name: "Steg 2: Skriv svar" });
    const rows = within(attempts).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]!).getByText(messages.flow_error_flow_provider_rate_limited)).toBeTruthy();
    expect(within(rows[1]!).getByText(/Modell model-large-2026/)).toBeTruthy();
    // The evidence says its credentials are masked.
    expect(screen.getByText(messages.flow_run_more_redacted)).toBeTruthy();

    const table = screen.getByRole("table", { name: messages.flow_run_extras_calls_heading });
    expect(within(table).getAllByRole("row")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: messages.flow_run_extras_calls_more }));
    await vi.waitFor(() => expect(within(table).getAllByRole("row")).toHaveLength(3));
    expect(calls(CALLS)[0]?.init.params?.query).toEqual({ after_event_id: "event-1", limit: 100 });
    expect(within(table).getByText(messages.flow_run_extras_call_outcome_unknown)).toBeTruthy();
    expect(screen.queryByRole("button", { name: messages.flow_run_extras_calls_more })).toBeNull();
    await expectNoAxeViolations(container);
  });

  it("keeps the trace as it is shown when the person comes back to the tab", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    state.routes[EVIDENCE] = () => ({ body: evidence() });
    state.routes[CALLS] = () => ({
      body: {
        count: 1,
        items: [call(2)],
        has_more: false,
        next_after_event_id: null,
        total_count: 2
      }
    });
    renderTrace();
    fireEvent.click(screen.getByRole("button", { name: messages.flow_run_extras_trace_show }));
    const table = await screen.findByRole("table", {
      name: messages.flow_run_extras_calls_heading
    });
    fireEvent.click(screen.getByRole("button", { name: messages.flow_run_extras_calls_more }));
    await vi.waitFor(() => expect(within(table).getAllByRole("row")).toHaveLength(3));

    await act(() => vi.advanceTimersByTimeAsync(31_000));
    act(() => {
      focusManager.setFocused(false);
      focusManager.setFocused(true);
    });
    focusManager.setFocused(undefined);
    await act(() => vi.advanceTimersByTimeAsync(100));
    expect(calls(EVIDENCE)).toHaveLength(1);
    // The calls read page by page are still there: the trace was not built again.
    expect(
      within(
        screen.getByRole("table", { name: messages.flow_run_extras_calls_heading })
      ).getAllByRole("row")
    ).toHaveLength(3);
  });

  it("writes out the diagnostic export only to copy or save it", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    state.routes[EVIDENCE] = () => ({ body: evidence() });
    const stringify = vi.spyOn(JSON, "stringify");
    const debugWrites = () =>
      stringify.mock.calls.filter(
        ([value]) =>
          (value as { schema_version?: string } | null)?.schema_version ===
          "eneo.flow.debug-export.v3"
      ).length;
    renderTrace();
    fireEvent.click(screen.getByRole("button", { name: messages.flow_run_extras_trace_show }));
    await screen.findByRole("button", { name: messages.flow_run_extras_debug_copy });
    expect(debugWrites()).toBe(0);

    fireEvent.click(screen.getByRole("button", { name: messages.flow_run_extras_debug_copy }));
    await vi.waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    expect(JSON.parse(writeText.mock.calls[0]![0] as string)).toEqual(evidence().debug_export);
    fireEvent.click(screen.getByRole("button", { name: messages.flow_run_extras_debug_download }));
    expect(state.saveBlob.mock.calls[0]?.[1]).toBe("flow-debug-export-run-1.json");
    expect(debugWrites()).toBe(2);
    stringify.mockRestore();
  });

  it("downloads the redacted export when the core allows it", async () => {
    state.routes[EXPORT] = () => ({ body: new Blob(["{}"], { type: "application/json" }) });
    const { container } = renderTrace();

    fireEvent.click(screen.getByRole("button", { name: messages.flow_run_extras_export_redacted }));
    await vi.waitFor(() => expect(state.saveBlob).toHaveBeenCalledTimes(1));
    expect(state.saveBlob.mock.calls[0]?.[1]).toBe("flow-run-evidence-run-1.json");
    expect(calls(EXPORT)[0]?.init.params?.query).toEqual({
      format: "json",
      detail: "redacted",
      reason: "support_debug"
    });
    expect(state.announce).toHaveBeenCalledWith(messages.flow_run_extras_export_done);
    await expectNoAxeViolations(container);
  });

  it("asks for a reason of one's own before the full export", async () => {
    state.routes[EXPORT] = () => ({ body: new Blob(["{}"], { type: "application/json" }) });
    renderTrace();

    fireEvent.click(
      screen.getByRole("button", { name: messages.flow_run_extras_export_raw_heading })
    );
    fireEvent.click(screen.getByRole("button", { name: messages.flow_run_extras_export_raw }));
    const reason = screen.getByRole("textbox", {
      name: new RegExp(messages.flow_run_extras_export_raw_reason)
    });
    expect(document.activeElement).toBe(reason);
    expect(screen.getByText(messages.flow_run_extras_export_raw_reason_required)).toBeTruthy();
    expect(calls(EXPORT)).toHaveLength(0);

    fireEvent.change(reason, { target: { value: "Begäran om allmän handling" } });
    fireEvent.click(screen.getByRole("button", { name: messages.flow_run_extras_export_raw }));
    await vi.waitFor(() => expect(calls(EXPORT)).toHaveLength(1));
    expect(calls(EXPORT)[0]?.init.params?.query).toEqual({
      format: "json",
      detail: "raw",
      reason: "Begäran om allmän handling"
    });
  });

  it("says export is off for a flow that does not allow it", () => {
    renderTrace({
      ...ALL_ALLOWED,
      can_export_redacted: false,
      can_export_raw: false,
      redacted_export_refusal_code: "flow_run_evidence_export_disabled",
      raw_export_refusal_code: "flow_run_evidence_export_disabled"
    });
    expect(screen.getByText(messages.flow_run_extras_export_off)).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: messages.flow_run_extras_export_redacted })
    ).toBeNull();
  });

  it("offers the redacted export and says why the full one is refused", () => {
    renderTrace({
      ...ALL_ALLOWED,
      can_export_raw: false,
      raw_export_refusal_code: "flow_run_evidence_raw_export_forbidden"
    });
    expect(
      screen.getByRole("button", { name: messages.flow_run_extras_export_redacted })
    ).toBeTruthy();
    expect(
      screen.getByText(messages.flow_error_flow_run_evidence_raw_export_forbidden)
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: messages.flow_run_extras_export_raw_heading })
    ).toBeNull();
  });
});
