// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { SpaceChat } from "./space-chat.client";

const route = vi.hoisted(() => ({
  space: {
    id: "space-1",
    name: "Upphandling",
    personal: false,
    organization: false,
    security_classification: null,
    default_assistant: null as unknown,
    completion_models: []
  }
}));
const api = vi.hoisted(() => ({
  GET: vi.fn(async () => ({
    data: undefined,
    error: { message: "Forbidden" },
    response: new Response(null, { status: 403 })
  })),
  POST: vi.fn(async (_path: string, init?: { body?: unknown }) => ({
    data: init?.body,
    response: new Response()
  }))
}));

/** A personal space whose assistant runs a model that offers reasoning levels. */
const reasoningModel = {
  id: "model-1",
  name: "gpt-5",
  nickname: "GPT-5",
  org: "OpenAI",
  max_input_tokens: 200000,
  reasoning: true,
  supported_model_kwargs: {
    reasoning_effort: { supported: true, control: "select", options: ["low", "medium", "high"] }
  }
};
const personalSpace = {
  ...route.space,
  personal: true,
  completion_models: [reasoningModel],
  default_assistant: {
    id: "assistant-1",
    name: "Default",
    completion_model: { id: "model-1", name: "gpt-5", nickname: "GPT-5" },
    completion_model_kwargs: { reasoning_effort: null },
    effective_config: {
      models_enforced: false,
      available_models: [],
      locked_model: null,
      default_model: null,
      mcp_enforced: false,
      prompt_locked: false,
      default_reasoning_effort: "medium",
      reasoning_effort_user_configurable: true
    },
    allowed_attachments: null,
    mcp_servers: [],
    enabled_capabilities: [],
    available_capabilities: []
  }
};

vi.mock("next/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", () => ({
  useSpace: () => ({ space: route.space, routeId: "space-1", can: () => true })
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

afterEach(() => {
  cleanup();
  api.GET.mockClear();
  api.POST.mockClear();
  route.space.personal = false;
  route.space.completion_models = [];
  route.space.default_assistant = null;
});

function renderRoute(url = "/spaces/space-1/chat") {
  return renderInApp(<SpaceChat />, { route: url });
}

describe("SpaceChat", () => {
  it("offers a retry when an assistant in the space can't be loaded", async () => {
    renderRoute("/spaces/space-1/chat?type=assistant&id=assistant-9");
    expect(await screen.findByText("Det gick inte att öppna chatten")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Försök igen" })).toBeTruthy();
  });

  it("says so without a retry when the space has no assistant to chat with", () => {
    renderRoute();
    expect(screen.getByText("Det gick inte att öppna chatten")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Försök igen" })).toBeNull();
    expect(api.GET).not.toHaveBeenCalled();
  });

  it("lets the personal assistant's reasoning effort be picked beside the model and saves it on the assistant", async () => {
    Object.assign(route.space, personalSpace);
    renderRoute("/spaces/personal/chat");

    const effort = await screen.findByRole("combobox", { name: "Resonemangsnivå: Medel" });
    // Beside the model picker, in the composer's send actions.
    expect(screen.getByRole("button", { name: /^Chattmodell: GPT-5/ })).toBeTruthy();
    fireEvent.click(effort);
    fireEvent.click(await screen.findByRole("option", { name: "Hög" }));

    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/assistants/{id}/", {
        params: { path: { id: "assistant-1" } },
        body: { completion_model_kwargs: { reasoning_effort: "high" } }
      })
    );
  });

  it("shows no reasoning picker when the policy keeps the level fixed", async () => {
    Object.assign(route.space, personalSpace, {
      default_assistant: {
        ...personalSpace.default_assistant,
        effective_config: {
          ...personalSpace.default_assistant.effective_config,
          reasoning_effort_user_configurable: false
        }
      }
    });
    renderRoute("/spaces/personal/chat");
    await screen.findByRole("button", { name: /^Chattmodell: GPT-5/ });
    expect(screen.queryByRole("combobox", { name: /^Resonemangsnivå/ })).toBeNull();
  });
});
