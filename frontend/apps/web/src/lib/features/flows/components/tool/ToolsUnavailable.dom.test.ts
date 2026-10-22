import { cleanup, render, screen } from "@testing-library/svelte";
import { readable } from "svelte/store";
import { afterEach, describe, expect, it, vi } from "vitest";

import { m } from "$lib/paraglide/messages";

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

const steps = () => screen.queryAllByRole("listitem").map((item) => item.textContent?.trim());
const settingsLink = () =>
  screen.queryByRole("link", { name: m.flow_tool_options_open_settings() });

describe("ToolsUnavailable in the step editor", () => {
  it.each([
    { mayEdit: true, owner: () => m.flow_tool_options_empty_editor() },
    { mayEdit: false, owner: () => m.flow_tool_options_empty_admin() }
  ])("says how the space gets a tool (editor: $mayEdit)", ({ mayEdit, owner }) => {
    space.mayEdit = mayEdit;
    render(ToolsUnavailable);

    expect(screen.getByText(m.flow_tool_options_empty())).toBeTruthy();
    expect(steps()).toEqual([
      m.flow_tool_options_empty_step_server(),
      owner(),
      m.flow_tool_options_empty_step_listed()
    ]);
  });

  it("says a personal space has no tools and offers no steps", () => {
    space.personal = true;
    render(ToolsUnavailable);

    expect(screen.getByText(m.flow_tool_refusal_space_is_personal())).toBeTruthy();
    expect(steps()).toEqual([]);
    expect(settingsLink()).toBeNull();
  });

  it.each([true, false])("links the space settings only for a space editor (%s)", (mayEdit) => {
    space.mayEdit = mayEdit;
    render(ToolsUnavailable);

    expect(settingsLink()?.getAttribute("href") ?? null).toBe(
      mayEdit ? "/spaces/space-1/settings" : null
    );
    expect(settingsLink()?.getAttribute("target") ?? null).toBe(mayEdit ? "_blank" : null);
  });
});
