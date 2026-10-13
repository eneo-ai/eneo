import { cleanup, render, screen } from "@testing-library/svelte";
import { createEneo, type FlowStep } from "@eneo/eneo-js";
import { get, readable } from "svelte/store";
import { afterEach, describe, expect, it, vi } from "vitest";

import { m } from "$lib/paraglide/messages";

import FlowValidationBanner from "./components/FlowValidationBanner.svelte";
import { readToolInputConfig } from "./components/tool/toolInputConfig";
import { createFlowEditor, describeFlowSaveRefusal } from "./FlowEditor";
import { flowFixture, flowStepFixture } from "./flowStepTestFixture";

vi.mock("$lib/features/spaces/SpacesManager", () => ({
  getSpacesManager: () => ({ state: { currentSpace: readable({ completion_models: [] }) } })
}));

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const TOOL = { mcp_server_id: "server-1", tool_id: "tool-search" };
const OPTION = {
  ...TOOL,
  mcp_server_name: "Ärenden",
  tool_name: "search_cases",
  tool_description: null,
  refusal: null,
  input_schema: { type: "object", required: ["query"], properties: { query: { type: "string" } } }
};

function secondStep(overrides: Partial<FlowStep>): FlowStep {
  return flowStepFixture({
    id: "step-2",
    assistant_id: "assistant-2",
    step_order: 2,
    ...overrides
  });
}

function toolStep(args: Record<string, unknown> | null): FlowStep {
  return secondStep({
    input_source: "tool",
    input_config: args ? { tool: { ...TOOL, arguments: args } } : null
  });
}

/** An editor on a two-step flow, through a real client whose requests are answered here. */
function editorFor(
  second: FlowStep,
  toolOptions: () => Response | Promise<Response> = () => Response.json({ items: [OPTION] })
) {
  const flow = flowFixture({ steps: [flowStepFixture({ user_description: "Hämta" }), second] });
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) =>
    String(input).includes("/tool-options") ? toolOptions() : Response.json(flow)
  );
  vi.stubGlobal("fetch", fetchMock);
  const editor = createFlowEditor({
    flow,
    eneo: createEneo({ baseUrl: "https://eneo.example", token: "test-user-token" })
  });
  const saves = () => fetchMock.mock.calls.filter(([, init]) => init?.method === "PATCH").length;
  return { editor, saves };
}

describe("FlowEditor with a tool step", () => {
  // Kills: a rename leaves a tool argument pointing at the old name; a rename
  // rewrites a fixed value, or loses an argument named like a member every
  // object has.
  it("follows a renamed step and a renamed form field in whole-variable arguments only", async () => {
    const fixed = "se {{Hämta}} för {{flow_input.kund}}";
    const named = (result: string, customer: string) =>
      Object.fromEntries([
        ["result", result],
        ["customer", customer],
        ["__proto__", fixed]
      ]);
    const { editor } = editorFor(toolStep(named("{{Hämta}}", "{{flow_input.kund}}")));

    await editor.rewriteStepNameVariableReferences({
      renamedStepOrder: 1,
      oldName: "Hämta",
      newName: "Läs in"
    });
    await editor.rewriteInputFieldVariableReferences("kund", "klient");

    const stored = readToolInputConfig(get(editor.state.update).steps?.[1].input_config);
    expect(Object.entries(stored?.arguments ?? {})).toEqual(
      Object.entries(named("{{Läs in}}", "{{flow_input.klient}}"))
    );
  });

  // Kills: a tool step without a chosen tool is sent to the server; a tool step
  // is never saved.
  it("holds the save back until the tool step names a tool", async () => {
    vi.useFakeTimers();
    const { editor, saves } = editorFor(secondStep({ input_source: "previous_step" }));

    editor.replaceStepAtIndex(1, toolStep(null));
    await vi.advanceTimersByTimeAsync(1000);
    expect(saves()).toBe(0);
    // Kills: a save held back for an issue the banner shows says "wait a moment".
    const refusal = await editor.flushFlowSaves().catch((error: unknown) => error);
    expect(describeFlowSaveRefusal(refusal, () => false)).toEqual({
      sentence: m.flow_validation_save_rejected(),
      issuesInBanner: true
    });

    editor.replaceStepAtIndex(1, toolStep({ query: "bygglov" }));
    await vi.advanceTimersByTimeAsync(1000);
    expect(saves()).toBeGreaterThan(0);
  });

  // Kills: a required argument without a value is no issue of the step, or
  // the issue does not name the argument.
  it("lists a required argument without a value among the step's issues", async () => {
    const { editor } = editorFor(toolStep({}));
    await vi.waitFor(() => expect(get(editor.state.validationErrors).size).toBe(1));

    render(FlowValidationBanner, {
      errors: get(editor.state.validationErrors),
      steps: get(editor.state.update).steps ?? [],
      isExpanded: true
    });
    expect(screen.getByText(m.flow_tool_argument_missing({ name: "query" }))).toBeTruthy();
  });

  // Kills: asking for the list again drops the list that is shown; the answer
  // of an earlier request replaces a later one's.
  it("keeps the list while it is asked for again, and the last request's answer", async () => {
    const answers: Array<(items: unknown[]) => void> = [];
    const { editor } = editorFor(
      toolStep({ query: "x" }),
      () => new Promise((resolve) => answers.push((items) => resolve(Response.json({ items }))))
    );
    const list = () => get(editor.state.toolOptions);
    await vi.waitFor(() => expect(answers).toHaveLength(1));
    answers[0]([OPTION]);
    await vi.waitFor(() => expect(list().status).toBe("loaded"));

    void editor.loadToolOptions();
    void editor.loadToolOptions();
    expect(list()).toEqual({ status: "loaded", options: [OPTION], refreshing: true });
    await vi.waitFor(() => expect(answers).toHaveLength(3));
    answers[2]([]);
    answers[1]([OPTION, OPTION]);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(list()).toEqual({ status: "loaded", options: [], refreshing: false });
  });
});
