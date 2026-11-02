import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getModelKwargOptionLabel } from "$lib/features/ai-models/ModelKwargCapabilities";
import { m } from "$lib/paraglide/messages";

const settingsMock = vi.hoisted(() => ({
  resolution: {
    reasoning_effort_options: ["none", "low", "medium", "high", "xhigh"],
    effective_reasoning_effort: "high",
    default_reasoning_effort: "medium",
    model_unavailable: false
  },
  settingsBusy: false,
  updateSettings: vi.fn()
}));
vi.mock("../../ChatService.svelte", () => ({
  getChatService: () => ({
    settings: { reasoning_effort: "high" },
    settingsResolution: settingsMock.resolution,
    get settingsBusy() {
      return settingsMock.settingsBusy;
    },
    askQuestion: { isLoading: false },
    updateSettings: settingsMock.updateSettings
  })
}));
import ChatReasoningSelect from "./ChatReasoningSelect.svelte";

const triggerName = `${m.reasoning_effort()}: ${getModelKwargOptionLabel("high")}`;

describe("ChatReasoningSelect", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    settingsMock.resolution.reasoning_effort_options = ["none", "low", "medium", "high", "xhigh"];
    settingsMock.resolution.model_unavailable = false;
    settingsMock.settingsBusy = false;
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
    // The saved effort is unchanged (the save is pending or failed), so the
    // pick is not shown as selected.
    await trigger.click();
    await expect
      .element(page.getByRole("option", { name: getModelKwargOptionLabel("high"), exact: true }))
      .toHaveAttribute("aria-selected", "true");
    await expect
      .element(page.getByRole("option", { name: getModelKwargOptionLabel("xhigh"), exact: true }))
      .not.toHaveAttribute("aria-selected", "true");
  });

  it("stays usable while a change is being saved", async () => {
    settingsMock.settingsBusy = true;
    render(ChatReasoningSelect);

    await expect.element(page.getByRole("button", { name: triggerName })).toBeEnabled();
  });

  it("is disabled while the saved model is unavailable", async () => {
    settingsMock.resolution.model_unavailable = true;
    render(ChatReasoningSelect);

    await expect.element(page.getByRole("button", { name: triggerName })).toBeDisabled();
  });

  it("stays hidden when the organization forbids user overrides", async () => {
    settingsMock.resolution.reasoning_effort_options = [];
    render(ChatReasoningSelect);

    await expect
      .element(page.getByRole("button", { name: new RegExp(m.reasoning_effort()) }))
      .not.toBeInTheDocument();
  });
});
