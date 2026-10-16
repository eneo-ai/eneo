import { cleanup, render, screen } from "@testing-library/svelte";
import { readable } from "svelte/store";
import { afterEach, describe, expect, it, vi } from "vitest";

import { m } from "$lib/paraglide/messages";
import type { UnusableTool } from "$lib/features/flows/flowToolRefusal";

import ToolsUnavailable from "./ToolsUnavailable.svelte";

const space = vi.hoisted(() => ({ personal: false, mayEdit: true }));

vi.mock("$lib/features/spaces/SpacesManager", () => ({
  getSpacesManager: () => ({
    state: {
      currentSpace: readable({
        personal: space.personal,
        routeId: "space-1",
        hasPermission: () => space.mayEdit
      })
    }
  })
}));

afterEach(() => {
  cleanup();
  space.personal = false;
  space.mayEdit = true;
});

function unusable(overrides: Partial<UnusableTool>): UnusableTool {
  return {
    tool_name: "lookup",
    server_name: "Records",
    kind: "refused",
    refusal: "tool_switched_off_in_space",
    ...overrides
  };
}

const steps = () => screen.queryAllByRole("listitem").map((item) => item.textContent?.trim());
const settingsLink = () =>
  screen.queryByRole("link", { name: m.flow_tool_options_open_settings() });

describe("ToolsUnavailable in the AI Builder", () => {
  // Kills: a reason sentence other than the refusal owner's; the steps shown
  // for a tool no step can fix or in a personal space; the step editor's
  // "refresh the list" step in the Builder, which has no list.
  it.each([
    {
      tool: unusable({}),
      personal: false,
      reason: () => m.flow_tool_refusal_tool_switched_off_in_space(),
      showsSteps: true
    },
    {
      tool: unusable({ kind: "input_schema_invalid", refusal: null }),
      personal: false,
      reason: () => m.flow_tool_unusable_input_schema_invalid(),
      showsSteps: false
    },
    {
      tool: unusable({ kind: "input_schema_too_large", refusal: null }),
      personal: false,
      reason: () => m.flow_tool_unusable_input_schema_too_large(),
      showsSteps: false
    },
    {
      tool: unusable({ refusal: "space_is_personal" }),
      personal: true,
      reason: () => m.flow_tool_refusal_space_is_personal(),
      showsSteps: false
    }
  ])(
    "names the tool and says why ($tool.kind, $tool.refusal)",
    ({ tool, personal, reason, showsSteps }) => {
      space.personal = personal;
      render(ToolsUnavailable, { surface: "builder", unusable: tool });

      expect(
        screen.getByText(m.flow_tool_unavailable_title({ tool: "lookup", server: "Records" }))
      ).toBeTruthy();
      expect(screen.getByText(reason())).toBeTruthy();
      expect(steps()).toEqual(
        showsSteps
          ? [
              m.flow_tool_options_empty_step_server(),
              m.flow_tool_options_empty_editor(),
              m.flow_tool_unavailable_step_ask_again()
            ]
          : []
      );
    }
  );

  // Kills: the settings link offered to someone who may not edit the space,
  // or opened in the Builder's own tab.
  it.each([true, false])("links the space settings only for a space editor (%s)", (mayEdit) => {
    space.mayEdit = mayEdit;
    render(ToolsUnavailable, { surface: "builder", unusable: unusable({}) });

    expect(settingsLink()?.getAttribute("href") ?? null).toBe(
      mayEdit ? "/spaces/space-1/settings" : null
    );
    expect(settingsLink()?.getAttribute("target") ?? null).toBe(mayEdit ? "_blank" : null);
  });
});
