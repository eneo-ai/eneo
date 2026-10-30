// @vitest-environment jsdom
import { focusManager } from "@tanstack/react-query";
import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import type { Schema } from "@/lib/api/models";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { runStepViews } from "./run-progress";
import { makeRunGraph } from "./run-fixtures";
import type { RunEvidence } from "./runs-api";

const state = vi.hoisted(() => ({
  announce: vi.fn(),
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

import { RunKnowledge } from "./run-knowledge";

const EVIDENCE = "GET /api/v1/flows/{id}/runs/{run_id}/evidence/";

const steps = runStepViews(
  makeRunGraph([
    { order: 1, label: "Sök underlag", status: "completed" },
    { order: 2, label: "Läs varje källa", status: "failed" },
    { order: 3, label: "Transkribera", status: "completed" }
  ]),
  []
);

function reference(
  id: string,
  name: string,
  overrides: Partial<Schema<"FlowRunDebugRagReference">> = {}
): Schema<"FlowRunDebugRagReference"> {
  return {
    id,
    id_short: id,
    source_display_name: name,
    best_score: 0.82,
    matched_chunk_count: 2,
    recorded_passage_count: 2,
    usage_state: "inserted_into_prompt",
    ...overrides
  };
}

function evidence(traces: Schema<"FlowRunStepKnowledgeTrace">[]): RunEvidence {
  return {
    debug_export: { run: { summary: null } },
    knowledge_traces: traces
  } as unknown as RunEvidence;
}

function renderKnowledge() {
  return renderInApp(<RunKnowledge flowId="flow-1" runId="run-1" steps={steps} runSettled />);
}

async function open() {
  fireEvent.click(screen.getByRole("button", { name: messages.flow_runs_knowledge_show }));
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

describe("RunKnowledge", () => {
  it("reads the audited evidence only when asked", async () => {
    state.routes[EVIDENCE] = () => ({ body: evidence([]) });
    renderKnowledge();
    expect(state.stub.calls).toHaveLength(0);

    await open();
    expect(await screen.findByText(messages.flow_runs_knowledge_none)).toBeTruthy();
    expect(state.stub.calls).toHaveLength(1);
  });

  it("does not read the evidence again when the person comes back to the tab", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    state.routes[EVIDENCE] = () => ({ body: evidence([]) });
    renderKnowledge();
    await open();
    expect(await screen.findByText(messages.flow_runs_knowledge_none)).toBeTruthy();

    await act(() => vi.advanceTimersByTimeAsync(31_000));
    act(() => {
      focusManager.setFocused(false);
      focusManager.setFocused(true);
    });
    focusManager.setFocused(undefined);
    await act(() => vi.advanceTimersByTimeAsync(100));
    expect(state.stub.calls).toHaveLength(1);
  });

  it("shows how each step's search went, how long it took and what it found", async () => {
    state.routes[EVIDENCE] = () => ({
      body: evidence([
        {
          step_order: 1,
          rag: {
            status: "success",
            chunks_retrieved: 4,
            retrieval_duration_ms: 1234,
            sources_total: 2,
            sources_with_recorded_passages: 1,
            references: [
              reference("blob-1", "Plan- och bygglagen"),
              reference("blob-2", "Taxa", { best_score: 0.31, usage_state: "retrieved_candidate" })
            ]
          }
        },
        {
          step_order: 2,
          rag: {
            execution_mode: "per_source",
            mapped_calls_complete: false,
            sources_total: 1,
            sources: [
              {
                status: "success",
                chunks_retrieved: 1,
                retrieval_duration_ms: 40,
                references: [
                  reference("blob-3", "Riktlinjer", {
                    passages: [
                      {
                        chunk_no: 1,
                        score: 0.4,
                        text: null,
                        passage_bytes: 10,
                        recorded_bytes: 10,
                        recording: "complete",
                        disclosure: "text_withheld_sensitive_flow"
                      }
                    ]
                  })
                ]
              },
              {
                status: "timeout",
                chunks_retrieved: 0,
                retrieval_duration_ms: 30000,
                retrieval_error_type: "TimeoutError"
              }
            ]
          }
        },
        { step_order: 3, rag: { status: "skipped_transcribe_only" } }
      ])
    });
    const { container } = renderKnowledge();
    await open();

    const first = await screen.findByRole("region", { name: "Steg 1: Sök underlag" });
    expect(within(first).getByText(messages.flow_run_knowledge_status_success)).toBeTruthy();
    expect(
      within(first).getByText(/^Källor: 2 · Hämtade textavsnitt: 4 · Söktid: 1\s234\sms$/u)
    ).toBeTruthy();
    expect(within(first).getByText("Hög relevans · 82 %")).toBeTruthy();
    expect(within(first).getByText("Medelhög relevans · 31 %")).toBeTruthy();
    expect(within(first).getByText("Textavsnitt sparades för 1 av 2 källor.")).toBeTruthy();

    const second = screen.getByRole("region", { name: "Steg 2: Läs varje källa" });
    expect(within(second).getByText(messages.flow_run_knowledge_status_timeout)).toBeTruthy();
    expect(within(second).getByText("TimeoutError")).toBeTruthy();
    expect(within(second).getByText(/Söktid: 30\s040\sms/u)).toBeTruthy();
    expect(within(second).getByText("Anrop 1")).toBeTruthy();
    expect(
      within(second).getByText(messages.flow_run_knowledge_passages_withheld_badge)
    ).toBeTruthy();
    expect(
      within(second).getByText(messages.flow_run_knowledge_mapped_fan_out_incomplete)
    ).toBeTruthy();

    expect(screen.queryByRole("region", { name: "Steg 3: Transkribera" })).toBeNull();
    await expectNoAxeViolations(container);
  });

  it("says why a search was skipped", async () => {
    state.routes[EVIDENCE] = () => ({
      body: evidence([{ step_order: 1, rag: { status: "skipped_no_input" } }])
    });
    renderKnowledge();
    await open();

    const first = await screen.findByRole("region", { name: "Steg 1: Sök underlag" });
    expect(
      within(first).getByText(messages.flow_run_knowledge_status_skipped_no_input)
    ).toBeTruthy();
    expect(within(first).queryByText(messages.flow_runs_knowledge_nothing_found)).toBeNull();
  });

  it("lists the first sources and finds the rest in the all-sources dialog", async () => {
    const names = ["Alfa", "Beta", "Gamma", "Delta", "Epsilon", "Zeta"];
    state.routes[EVIDENCE] = () => ({
      body: evidence([
        {
          step_order: 1,
          rag: {
            status: "success",
            chunks_retrieved: 6,
            references: names.map((name, index) => reference(`blob-${index}`, name))
          }
        }
      ])
    });
    const { baseElement } = renderKnowledge();
    await open();

    const first = await screen.findByRole("region", { name: "Steg 1: Sök underlag" });
    expect(within(first).getByRole("button", { name: "Visa källan Delta" })).toBeTruthy();
    expect(within(first).queryByRole("button", { name: "Visa källan Epsilon" })).toBeNull();
    expect(within(first).getByText("Visar 4 av 6 källor här.")).toBeTruthy();

    fireEvent.click(within(first).getByRole("button", { name: "Visa alla 6 källor" }));
    const dialog = await screen.findByRole("dialog", {
      name: messages.flow_run_knowledge_all_sources_title
    });
    expect(within(dialog).getByRole("button", { name: "Visa källan Zeta" })).toBeTruthy();

    fireEvent.change(
      within(dialog).getByRole("textbox", { name: messages.flow_run_ktrace_search_sources }),
      { target: { value: "eps" } }
    );
    expect(within(dialog).getByRole("button", { name: "Visa källan Epsilon" })).toBeTruthy();
    expect(within(dialog).queryByRole("button", { name: "Visa källan Zeta" })).toBeNull();
    expect(within(dialog).getByText("Visar 1 av 1 matchande källor.")).toBeTruthy();

    fireEvent.change(
      within(dialog).getByRole("textbox", { name: messages.flow_run_ktrace_search_sources }),
      { target: { value: "saknas" } }
    );
    expect(within(dialog).getByText(messages.flow_run_knowledge_no_matching_sources)).toBeTruthy();
    await expectNoAxeViolations(baseElement);
  });
});
