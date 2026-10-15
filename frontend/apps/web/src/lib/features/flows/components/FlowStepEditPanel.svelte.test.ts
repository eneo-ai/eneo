import { page } from "@vitest/browser/context";
import { createEneo, type FlowStep } from "@eneo/eneo-js";
import { get, readable } from "svelte/store";
import { render } from "vitest-browser-svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import "../../../../app.css";

import type { FlowEditor } from "$lib/features/flows/FlowEditor";
import { flowFixture, flowStepFixture } from "$lib/features/flows/flowStepTestFixture";
import { m } from "$lib/paraglide/messages";

import FlowStepEditPanelHarness from "./test-harnesses/FlowStepEditPanelHarness.svelte";

vi.mock("$lib/features/spaces/SpacesManager", () => ({
  getSpacesManager: () => ({
    state: {
      currentSpace: readable({
        id: "space-1",
        personal: false,
        routeId: "space-1",
        completion_models: [],
        hasPermission: () => false
      })
    }
  })
}));

afterEach(() => {
  vi.unstubAllGlobals();
});

const SEARCH = {
  mcp_server_id: "server-1",
  mcp_server_name: "Ärenden",
  mcp_server_security_level: null,
  tool_id: "tool-search",
  tool_name: "search_cases",
  tool_description: null,
  input_schema: {
    type: "object",
    required: ["query"],
    properties: { query: { type: "string" } }
  },
  refusal: null
};

function toolStep(order: number): FlowStep {
  return flowStepFixture({
    id: `step-${order}`,
    assistant_id: `assistant-${order}`,
    step_order: order,
    user_description: `Hämta ${order}`,
    input_source: "tool",
    input_config: {
      tool: { mcp_server_id: "server-1", tool_id: "tool-search", arguments: { query: "x" } }
    }
  });
}

/**
 * The step editor on a two-step flow whose steps both read the tool, through
 * a real client whose requests are answered here; the tool list answers when
 * the test says so.
 */
async function mountEditor() {
  const flow = flowFixture({ steps: [toolStep(1), toolStep(2)] });
  let answerToolList: () => void = () => {};
  const toolList = new Promise<Response>((resolve) => {
    answerToolList = () =>
      resolve(Response.json({ items: [SEARCH], security_classifications_enabled: false }));
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input instanceof Request ? input.url : input);
      if (url.includes("/tool-options")) return toolList;
      if (url.includes("/prompts/")) return Response.json({ items: [] });
      if (url.includes("/assistants/")) {
        return Response.json({ id: url.split("/").filter(Boolean).at(-1), prompt: { text: "" } });
      }
      return Response.json(flow);
    })
  );
  let editor: FlowEditor | undefined;
  render(FlowStepEditPanelHarness, {
    flow,
    eneo: createEneo({ baseUrl: "https://eneo.example", token: "test-user-token" }),
    onEditor: (created: FlowEditor) => (editor = created)
  });
  if (!editor) throw new Error("the harness created no editor");
  return { editor, answerToolList };
}

// The chapter's button; while it is closed, its name ends with the chapter's summary.
const underlag = () =>
  page.getByRole("button", { name: new RegExp(`^${m.flow_chapter_input()}(\\s|$)`) });
const picker = () => page.getByRole("combobox", { name: /search_cases/ }).element();

// A real browser: the Underlag chapter waits for its opening animation, which
// jsdom does not have, before it lands.
describe("FlowStepEditPanel landing where the banner's Go to step asks", () => {
  // Kills: the panel hands the Underlag chapter no place to land on; it hands
  // it over while the tool list still loads, so the request is spent before
  // the picker exists; the request is not handed back, so a later visit to
  // the step lands again; the chapter summary does not name the chosen tool.
  it("lands on the place in the step once the tool list is there, and hands the request back", async () => {
    const { editor, answerToolList } = await mountEditor();
    editor.selectStep("step-1");

    editor.goToStep("step-2", { kind: "tool" });
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(get(editor.state.stepFocusRequest)).toStrictEqual({ kind: "tool" });

    answerToolList();
    await vi.waitFor(() => expect(document.activeElement).toBe(picker()));
    expect(get(editor.state.stepFocusRequest)).toBeNull();

    await underlag().click();
    await expect.element(underlag()).toHaveTextContent(/search_cases/);
  });

  // Kills: a landing still waiting for the chapter to open lands in the step
  // the author switched to meanwhile.
  it("does not land in another step the author opens while the chapter opens", async () => {
    const { editor, answerToolList } = await mountEditor();
    answerToolList();
    editor.selectStep("step-1");
    await expect.element(underlag()).toBeVisible();
    if (underlag().element().getAttribute("aria-expanded") === "false") await underlag().click();
    await expect.element(page.getByRole("combobox", { name: /search_cases/ })).toBeVisible();

    const unsubscribe = editor.state.stepFocusRequest.subscribe((request) => {
      if (request === null && get(editor.state.activeStepId) === "step-2") {
        editor.selectStep("step-1");
      }
    });
    editor.goToStep("step-2", { kind: "tool" });
    await vi.waitFor(() => expect(get(editor.state.activeStepId)).toBe("step-1"));
    await new Promise((resolve) => setTimeout(resolve, 600));
    unsubscribe();

    expect(document.activeElement).not.toBe(picker());
  });
});
