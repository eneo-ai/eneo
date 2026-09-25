import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getModelKwargOptionLabel } from "$lib/features/ai-models/ModelKwargCapabilities";
import { m } from "$lib/paraglide/messages";

const spacesManagerMock = vi.hoisted(() => {
  type SpaceState = {
    default_assistant: {
      completion_model: { id: string };
      completion_model_kwargs: { reasoning_effort: string | null };
      effective_config: {
        models_enforced: boolean;
        available_models: { id: string }[];
        default_model: { id: string } | null;
        locked_model: { id: string } | null;
        reasoning_effort_user_configurable: boolean;
        default_reasoning_effort: string | null;
      };
    };
    completion_models: {
      id: string;
      supported_model_kwargs: {
        reasoning_effort: {
          supported: boolean;
          control: "select";
          options: string[];
        };
      };
    }[];
  };

  let current: SpaceState;
  const subscribers = new Set<(space: SpaceState) => void>();

  return {
    currentSpace: {
      subscribe: (run: (space: SpaceState) => void) => {
        subscribers.add(run);
        run(current);
        return () => subscribers.delete(run);
      }
    },
    setSpace: (space: SpaceState) => {
      current = space;
      subscribers.forEach((run) => run(current));
    },
    updateDefaultAssistant: vi.fn()
  };
});

vi.mock("$lib/features/spaces/SpacesManager", () => ({
  getSpacesManager: () => ({
    state: { currentSpace: spacesManagerMock.currentSpace },
    updateDefaultAssistant: spacesManagerMock.updateDefaultAssistant
  })
}));

import ChatReasoningSelect from "./ChatReasoningSelect.svelte";

function reasoningSpace(userConfigurable = true) {
  const model = {
    id: "reasoning-model",
    supported_model_kwargs: {
      reasoning_effort: {
        supported: true,
        control: "select" as const,
        options: ["none", "low", "medium", "high", "xhigh"]
      }
    }
  };

  return {
    default_assistant: {
      completion_model: model,
      completion_model_kwargs: { reasoning_effort: "high" },
      effective_config: {
        models_enforced: false,
        available_models: [],
        default_model: null,
        locked_model: null,
        reasoning_effort_user_configurable: userConfigurable,
        default_reasoning_effort: "medium"
      }
    },
    completion_models: [model]
  };
}

describe("ChatReasoningSelect", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    spacesManagerMock.setSpace(reasoningSpace());
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

    expect(spacesManagerMock.updateDefaultAssistant).toHaveBeenCalledWith({
      modelKwargs: { reasoning_effort: "xhigh" }
    });
  });

  it("stays hidden when the organization forbids user overrides", async () => {
    spacesManagerMock.setSpace(reasoningSpace(false));
    render(ChatReasoningSelect);

    await expect
      .element(page.getByRole("button", { name: new RegExp(m.reasoning_effort()) }))
      .not.toBeInTheDocument();
  });
});
