import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { get, writable } from "svelte/store";
import type { components } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";
import { CAPABILITIES, type CapabilityPurpose } from "$lib/features/mcp/capabilities";

type SpaceState = {
  enabled_capabilities: CapabilityPurpose[];
  available_capabilities: components["schemas"]["CapabilityAvailability"][];
};
const currentSpace = writable<SpaceState>({ enabled_capabilities: [], available_capabilities: [] });
const updateSpace = vi.fn(async (update: { enabled_capabilities: CapabilityPurpose[] }) => {
  currentSpace.update((space) => ({ ...space, ...update }));
  return get(currentSpace);
});
vi.mock("$lib/features/spaces/SpacesManager", () => ({
  getSpacesManager: () => ({ state: { currentSpace }, updateSpace })
}));
import CapabilityToggle from "./CapabilityToggle.svelte";
import CapabilityRow from "../../../../routes/(app)/spaces/[spaceId]/settings/CapabilityRow.svelte";
import PolicyFunctions from "./PolicyFunctions.svelte";

const capability = CAPABILITIES[0];
const available = { purpose: "web_search" as const, available: true, reason: null };
const control = () => page.getByRole("switch", { name: m.web_search(), exact: false });

beforeEach(() => {
  vi.clearAllMocks();
  currentSpace.set({ enabled_capabilities: ["web_search"], available_capabilities: [available] });
});

describe("assistant function settings", () => {
  it("explains when an otherwise available function is disabled in the space", async () => {
    currentSpace.update((space) => ({ ...space, enabled_capabilities: [] }));
    render(CapabilityToggle, { capability });
    await expect.element(control()).toBeDisabled();
    await expect.element(page.getByText(m.tools_readiness_space_disabled())).toBeVisible();
    await expect.element(page.getByText(m.not_available(), { exact: true })).toBeVisible();
    expect(page.getByText(m.tools_readiness_no_active_provider()).elements()).toHaveLength(0);
  });

  it("explains a missing provider when the space allows the function", async () => {
    currentSpace.update((space) => ({
      ...space,
      available_capabilities: [{ ...available, available: false, reason: "no_active_provider" }]
    }));
    render(CapabilityToggle, { capability });
    await expect.element(control()).toBeDisabled();
    await expect.element(page.getByText(m.tools_readiness_no_active_provider())).toBeVisible();
  });

  it("blocks newly enabling a function with a model that cannot call tools", async () => {
    render(CapabilityToggle, { capability, selectedModel: { supports_tool_calling: false } });
    await expect.element(control()).toBeDisabled();
    await expect.element(page.getByText(m.model_does_not_support_tools())).toBeVisible();
  });

  it("allows turning off a saved function even with space and model restrictions", async () => {
    currentSpace.update((space) => ({ ...space, enabled_capabilities: [] }));
    render(CapabilityToggle, {
      capability,
      enabledCapabilities: ["web_search"],
      selectedModel: { supports_tool_calling: false }
    });
    await expect.element(control()).not.toBeDisabled();
    await control().click();
    await expect.element(control()).toHaveAttribute("aria-checked", "false");
    await expect.element(control()).toBeDisabled();
  });

  it("allows enabling an available function with a compatible model", async () => {
    render(CapabilityToggle, { capability, selectedModel: { supports_tool_calling: true } });
    await expect.element(control()).toHaveAttribute("aria-checked", "false");
    expect(page.getByText(m.not_available(), { exact: true }).elements()).toHaveLength(0);
    await control().click();
    await expect.element(control()).toHaveAttribute("aria-checked", "true");
  });
});

describe("space function settings", () => {
  it("restores the saved switch state when saving fails", async () => {
    currentSpace.update((space) => ({ ...space, enabled_capabilities: [] }));
    updateSpace.mockRejectedValueOnce(new Error("Save failed"));
    render(CapabilityRow, { capability });
    await control().click();
    await expect.element(page.getByRole("alert")).toHaveTextContent(m.request_failed());
    await expect.element(control()).toHaveAttribute("aria-checked", "false");
  });

  it("restores the saved state when the space manager handles the failure", async () => {
    currentSpace.update((space) => ({ ...space, enabled_capabilities: [] }));
    updateSpace.mockResolvedValueOnce(undefined as never);
    render(CapabilityRow, { capability });
    await control().click();
    await vi.waitFor(() =>
      expect(updateSpace).toHaveBeenCalledWith({ enabled_capabilities: ["web_search"] })
    );
    await expect.element(control()).toHaveAttribute("aria-checked", "false");
  });

  it("saves disabling an unavailable function while preserving other selections", async () => {
    currentSpace.set({
      enabled_capabilities: ["web_search", "image_generation"],
      available_capabilities: []
    });
    render(CapabilityRow, { capability });
    await expect.element(page.getByText(m.not_available(), { exact: true })).toBeVisible();
    await control().click();
    await vi.waitFor(() =>
      expect(updateSpace).toHaveBeenCalledWith({ enabled_capabilities: ["image_generation"] })
    );
    await expect.element(control()).toHaveAttribute("aria-checked", "false");
    await expect.element(control()).toBeDisabled();
  });
});

describe("policy function settings", () => {
  it("shows policy-granted functions, chat defaults and temporary unavailability without edit controls", async () => {
    render(PolicyFunctions, {
      config: {
        enabled_capabilities: ["web_search", "image_generation"],
        default_disabled_capabilities: ["image_generation"],
        available_capabilities: [
          available,
          { purpose: "image_generation", available: false, reason: "model_disabled" }
        ]
      }
    });
    await expect.element(page.getByText(m.web_search(), { exact: true })).toBeVisible();
    await expect.element(page.getByText(m.image_generation(), { exact: true })).toBeVisible();
    await expect.element(page.getByText(m.functions_default_on())).toBeVisible();
    await expect.element(page.getByText(m.functions_default_off())).toBeVisible();
    await expect.element(page.getByText(m.tools_readiness_model_disabled())).toBeVisible();
    expect(page.getByRole("switch").elements()).toHaveLength(0);
  });
});
