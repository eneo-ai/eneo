import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
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
  mcp_server_security_level: null,
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
  toolOptions: () => Response | Promise<Response> = () =>
    Response.json({ items: [OPTION], security_classifications_enabled: true })
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

  // Kills: an arguments text the step cannot hold is no issue of the step, so
  // publish stays open with the old arguments; the issue is lost when a save
  // hands the arguments back with their keys in another order; "Go to step"
  // does not land on the arguments; the issue stays once the step holds other
  // arguments, comes back when the step holds the old arguments again, or
  // outlives its step.
  it("counts an arguments text the step cannot hold as its issue while the step holds what it was typed against", async () => {
    const { editor } = editorFor(toolStep({ query: "x", limit: 5 }));
    await vi.waitFor(() => expect(get(editor.state.toolOptions).status).toBe("loaded"));
    const typedAgainst = { ...TOOL, arguments: { limit: 5, query: "x" } };

    editor.keepToolArgumentsDraft(get(editor.state.update).steps?.[1] as FlowStep, "arguments", {
      text: '{"query": ',
      scope: { except: [] },
      typedAgainst
    });
    const onNavigateToStep = vi.fn();
    render(FlowValidationBanner, {
      errors: get(editor.state.validationErrors),
      steps: get(editor.state.update).steps ?? [],
      onNavigateToStep,
      isExpanded: true
    });
    expect(screen.getByText(m.flow_tool_arguments_unsaved())).toBeTruthy();
    await fireEvent.click(screen.getByRole("button", { name: m.flow_validation_go_to_step() }));
    expect(onNavigateToStep).toHaveBeenCalledWith("step-2", { kind: "tool_arguments" });

    editor.replaceStepAtIndex(1, toolStep({ query: "y" }));
    expect(get(editor.state.validationErrors).size).toBe(0);
    // The replaced text does not return with the values it was typed against.
    editor.replaceStepAtIndex(1, toolStep({ query: "x", limit: 5 }));
    expect(get(editor.state.validationErrors).size).toBe(0);
    expect(get(editor.state.toolArgumentsDrafts).size).toBe(0);
    // Nor is a removed step's text kept.
    editor.keepToolArgumentsDraft(get(editor.state.update).steps?.[1] as FlowStep, "arguments", {
      text: "{",
      scope: { except: [] },
      typedAgainst
    });
    await editor.removeStepAtIndex(1);
    expect(get(editor.state.toolArgumentsDrafts).size).toBe(0);
  });

  // Kills: "Go to step" asks for no place, or for one in a step that is not
  // shown; a request outlives a move to another step (the graph, the Builder,
  // the step list), so the step editor lands there on a later visit.
  it("asks the step editor for a place in the step it shows, until another step is shown", () => {
    const { editor } = editorFor(toolStep({ query: "x" }));
    const request = () => get(editor.state.stepFocusRequest);

    editor.goToStep("step-2", { kind: "tool" });
    expect([get(editor.state.activeStepId), request()]).toStrictEqual(["step-2", { kind: "tool" }]);
    editor.selectStep("step-1");
    expect(request()).toBeNull();
    editor.goToStep("step-9", { kind: "tool" });
    expect([get(editor.state.activeStepId), request()]).toStrictEqual(["step-1", null]);
  });

  // Kills: asking for the list again drops the list that is shown; the answer
  // of an earlier request replaces a later one's.
  it("keeps the list while it is asked for again, and the last request's answer", async () => {
    const answers: Array<(items: unknown[]) => void> = [];
    const { editor } = editorFor(
      toolStep({ query: "x" }),
      () =>
        new Promise((resolve) =>
          answers.push((items) =>
            resolve(Response.json({ items, security_classifications_enabled: true }))
          )
        )
    );
    const list = () => get(editor.state.toolOptions);
    await vi.waitFor(() => expect(answers).toHaveLength(1));
    answers[0]([OPTION]);
    await vi.waitFor(() => expect(list().status).toBe("loaded"));

    void editor.loadToolOptions();
    void editor.loadToolOptions();
    expect(list()).toEqual({
      status: "loaded",
      options: [OPTION],
      classificationsEnabled: true,
      refreshing: true
    });
    await vi.waitFor(() => expect(answers).toHaveLength(3));
    answers[2]([]);
    answers[1]([OPTION, OPTION]);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(list()).toEqual({
      status: "loaded",
      options: [],
      classificationsEnabled: true,
      refreshing: false
    });
  });
});
