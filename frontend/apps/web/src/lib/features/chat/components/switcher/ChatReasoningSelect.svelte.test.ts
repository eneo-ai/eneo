import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getModelKwargOptionLabel } from "$lib/features/ai-models/ModelKwargCapabilities";
import { m } from "$lib/paraglide/messages";

const settingsMock = vi.hoisted(() => ({
  resolution: {
    reasoning_effort_options: ["none", "low", "medium", "high", "xhigh"],
    effective_reasoning_effort: "high",
    default_reasoning_effort: "medium"
  },
  updateSettings: vi.fn()
}));
vi.mock("../../ChatService.svelte", () => ({
  getChatService: () => ({
    settings: { reasoning_effort: "high" },
    settingsResolution: settingsMock.resolution,
    settingsBusy: false,
    askQuestion: { isLoading: false },
    updateSettings: settingsMock.updateSettings
  })
}));
import ChatReasoningSelect from "./ChatReasoningSelect.svelte";

describe("ChatReasoningSelect", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    settingsMock.resolution.reasoning_effort_options = ["none", "low", "medium", "high", "xhigh"];
  });

  it("shows the selected model's exact levels and persists only the chosen effort", async () => {
    render(ChatReasoningSelect);

    const trigger = page.getByRole("button", {
      name: `${m.reasoning_effort()}: ${getModelKwargOptionLabel("high")}`
    });
    await trigger.click();

    await expect
      .element(page.getByRole("option", { name: getModelKwargOptionLabel("none") }))
      .toBeVisible();
    await expect
      .element(page.getByRole("option", { name: getModelKwargOptionLabel("xhigh") }))
      .toBeVisible();
    await expect
      .element(page.getByRole("option", { name: getModelKwargOptionLabel("max") }))
      .not.toBeInTheDocument();

    await page.getByRole("option", { name: getModelKwargOptionLabel("xhigh") }).click();

    expect(settingsMock.updateSettings).toHaveBeenCalledWith({
      reasoning_effort: "xhigh"
    });
  });

  it("stays hidden when the organization forbids user overrides", async () => {
    settingsMock.resolution.reasoning_effort_options = [];
    render(ChatReasoningSelect);

    await expect
      .element(page.getByRole("button", { name: new RegExp(m.reasoning_effort()) }))
      .not.toBeInTheDocument();
  });
});
