import { page } from "@vitest/browser/context";
import { readable } from "svelte/store";
import { render } from "vitest-browser-svelte";
import { describe, expect, it, vi } from "vitest";
import "../../../../app.css";

import { flowStepFixture } from "$lib/features/flows/flowStepTestFixture";
import type { StepFocusTarget } from "$lib/features/flows/flowStepFocus";
import { m } from "$lib/paraglide/messages";

import FlowStepChapterToolHarness from "./test-harnesses/FlowStepChapterToolHarness.svelte";

vi.mock("$lib/features/spaces/SpacesManager", () => ({
  getSpacesManager: () => ({
    state: {
      currentSpace: readable({ personal: false, routeId: "space-1", hasPermission: () => false })
    }
  })
}));

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
    properties: { query: { type: "string" }, limit: { type: "integer" } }
  },
  refusal: null
};

// A real browser: jsdom ignores `inert` and lays nothing out, so there focus
// "lands" inside a closed chapter and nothing is ever out of view.
describe("FlowStepChapter landing on a place in the tool section", () => {
  function inView(element: HTMLElement): boolean {
    const box = page.getByTestId("editor").element().getBoundingClientRect();
    const rect = element.getBoundingClientRect();
    return rect.top >= box.top && rect.bottom <= box.bottom && rect.height > 0;
  }

  // Kills: the closed chapter does not open, so the inert content cannot take
  // the focus; the place is scrolled to before the chapter has opened, so it
  // ends out of view; the place is not handed back (a later visit lands again).
  it.each<{ target: StepFocusTarget; focused: () => HTMLElement }>([
    {
      target: { kind: "tool" },
      focused: () => page.getByRole("combobox", { name: /search_cases/ }).element() as HTMLElement
    },
    {
      target: { kind: "tool_argument", name: "query" },
      focused: () =>
        page
          .getByRole("textbox", { name: m.flow_tool_argument_value_label({ argument: "query" }) })
          .element() as HTMLElement
    }
  ])(
    "opens, scrolls to and focuses $target, coming from another step",
    async ({ target, focused }) => {
      const onFocusTaken = vi.fn();
      const panel = {
        config: {
          mcp_server_id: "server-1",
          tool_id: "tool-search",
          arguments: {},
          hasOtherKeys: false
        },
        toolOptions: {
          status: "loaded" as const,
          options: [SEARCH],
          classificationsEnabled: false,
          refreshing: false
        },
        stepKey: "step-2",
        isPublished: false,
        variableContext: {
          steps: [flowStepFixture()],
          currentStepOrder: 2,
          formSchema: undefined,
          isAdvancedMode: true,
          transcriptionEnabled: false
        }
      };
      const view = render(FlowStepChapterToolHarness, {
        stepKey: "step-1",
        focusTarget: null,
        onFocusTaken,
        panel
      });
      await expect
        .element(page.getByRole("button", { name: m.flow_chapter_input() }))
        .toHaveAttribute("aria-expanded", "false");

      await view.rerender({ stepKey: "step-2", focusTarget: target, onFocusTaken, panel });

      await vi.waitFor(() => expect(document.activeElement).toBe(focused()));
      expect(inView(focused())).toBe(true);
      expect(onFocusTaken).toHaveBeenCalledTimes(1);
    }
  );
});
