// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { makeQueryClient } from "@/lib/api/query";
import { renderInApp, testAppContext, testQueryClient } from "@/test/render";
import { SpaceChat } from "@/features/spaces/chat/space-chat.client";

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
  GET: vi.fn(),
  POST: vi.fn(async (_path: string, init?: { body?: unknown; signal?: AbortSignal }) => ({
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
    permissions: ["read"],
    mcp_servers: [],
    enabled_capabilities: [],
    available_capabilities: []
  }
};

vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", () => ({
  useSpace: () => ({ space: route.space, routeId: "space-1", can: () => true })
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

beforeEach(() => {
  api.GET.mockImplementation(async () => ({
    data: undefined,
    error: { message: "Forbidden" },
    response: new Response(null, { status: 403 })
  }));
});

afterEach(() => {
  cleanup();
  api.GET.mockClear();
  api.POST.mockReset();
  api.POST.mockImplementation(async (_path, init) => ({
    data: init?.body,
    response: new Response()
  }));
  route.space.personal = false;
  route.space.completion_models = [];
  route.space.default_assistant = null;
});

function renderRoute(url = "/spaces/space-1/chat", permissions: string[] = []) {
  return renderInApp(<SpaceChat />, {
    route: url,
    appContext: testAppContext({ permissions: permissions as never })
  });
}

describe("SpaceChat", () => {
  it("offers a retry when an assistant in the space can't be loaded", async () => {
    renderRoute("/spaces/space-1/chat?type=assistant&id=assistant-9");
    expect(await screen.findByText("Det gick inte att öppna chatten")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Försök igen" })).toBeTruthy();
  });

  it.each([
    ["assistant", 403, 1],
    ["group-chat", 404, 1],
    ["assistant", 503, 2],
    ["group-chat", 503, 2]
  ] as const)(
    "sends the %s request after a %s %s time(s) in its first second, under the app's retry policy",
    async (type, status, requests) => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      try {
        api.GET.mockImplementation(async () => ({
          data: undefined,
          error: { message: "Failed" },
          response: new Response(null, { status })
        }));
        renderInApp(<SpaceChat />, {
          route: `/spaces/space-1/chat?type=${type}&id=partner-9`,
          queryClient: makeQueryClient()
        });
        await waitFor(() => expect(api.GET).toHaveBeenCalledTimes(1));
        // The first retry waits one second, the next two more.
        await act(() => vi.advanceTimersByTimeAsync(1_500));
        expect(api.GET).toHaveBeenCalledTimes(requests);
      } finally {
        vi.useRealTimers();
      }
    }
  );

  it("says so without a retry when the space has no assistant to chat with", () => {
    renderRoute();
    expect(screen.getByText("Det gick inte att öppna chatten")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Försök igen" })).toBeNull();
    expect(api.GET).not.toHaveBeenCalled();
  });

  it.each(["assistant", "group-chat"])("projects insight_view from the loaded %s", async (type) => {
    const queryClient = testQueryClient();
    queryClient.setQueryData([type === "assistant" ? "assistants" : "group-chats", "partner-9"], {
      ...personalSpace.default_assistant,
      id: "partner-9",
      name: "Avtalsgranskning",
      insight_enabled: true,
      permissions: ["read", "insight_view"],
      groups: [],
      websites: [],
      integration_knowledge_list: [],
      // A group chat always lists its member assistants (GroupChatPublic.tools).
      ...(type === "group-chat" && { tools: { assistants: [{ id: "member-1", handle: "avtal" }] } })
    });
    renderInApp(<SpaceChat />, {
      route: `/spaces/space-1/chat?type=${type}&id=partner-9`,
      queryClient
    });
    expect(await screen.findByRole("tab", { name: "Insikter" })).toBeTruthy();
  });

  it("refreshes the empty-draft baseline after a saved Skill change and a model switch", async () => {
    const assistant = { ...personalSpace.default_assistant };
    Object.assign(route.space, personalSpace, { default_assistant: assistant });
    const summary = {
      skill_id: "answers",
      skill_revision_id: "r1",
      attachable_revision_id: "r1",
      slug: "answers",
      display_name: "Mina svarspreferenser",
      description: "",
      content_digest: "digest",
      revision_number: 1,
      attachable_revision_number: 1,
      position: 0,
      is_active: true,
      source: "space",
      execution_blocked: false,
      activation_mode: "always"
    };
    let bindings = [summary];
    let configurationReads = 0;
    const requests: { signal: AbortSignal; resolve: (data: unknown) => void }[] = [];
    api.GET.mockImplementation(async (path: string) => {
      if (path === "/api/v1/dashboard/")
        return { data: { spaces: { items: [] } }, response: new Response() };
      if (path.endsWith("/skills/configuration/")) {
        configurationReads++;
        return {
          data: {
            bindings,
            organisation_bindings: [],
            personal_layer: { status: "applied", reason: null, detail: null },
            runtime: null
          },
          response: new Response()
        };
      }
      return { data: { items: [], total_count: 0, next_cursor: null }, response: new Response() };
    });
    api.POST.mockImplementation(async (path, init) => {
      if (path === "/api/v1/conversations/preflight")
        return new Promise((resolve) => {
          requests.push({
            signal: init!.signal!,
            resolve: (data) => resolve({ data, response: new Response() })
          });
        });
      bindings = [];
      return { data: init?.body, response: new Response() };
    });
    const view = renderInApp(<SpaceChat />, {
      route: "/spaces/personal/chat",
      appContext: testAppContext({ permissions: ["personal_chat", "personal_skills"] })
    });
    await waitFor(() => expect(requests).toHaveLength(1));
    expect(configurationReads).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: /^Skills/ }));
    const mode = await screen.findByRole("radiogroup", { name: "Läge för Mina svarspreferenser" });
    fireEvent.click(within(mode).getByRole("radio", { name: "Av" }));
    await waitFor(() => expect(configurationReads).toBe(3));
    await waitFor(() => expect(requests).toHaveLength(2));
    expect(requests[0]!.signal.aborted).toBe(true);
    await act(async () =>
      requests[0]!.resolve({
        input_tokens: 0,
        file_tokens: 0,
        prompt_tokens: 9999,
        context_window: 10000
      })
    );
    expect(screen.queryByRole("button", { name: /^Kontextanvändning:/ })).toBeNull();
    assistant.completion_model = { ...assistant.completion_model, id: "model-2" };
    view.rerender(<SpaceChat />);
    await waitFor(() => expect(requests).toHaveLength(3));
    expect(requests[1]!.signal.aborted).toBe(true);
    await act(async () =>
      requests[2]!.resolve({
        input_tokens: 0,
        file_tokens: 0,
        prompt_tokens: 500,
        skill_context_tokens: 200,
        assistant_attachment_tokens: 300,
        context_window: 10000
      })
    );
    expect(
      (await screen.findByRole("button", { name: /^Kontextanvändning:/ })).textContent
    ).toMatch(/800 \/ 10.000/);
  });

  it("denies a loaded personal assistant without read access before private queries mount", () => {
    Object.assign(route.space, personalSpace, {
      default_assistant: { ...personalSpace.default_assistant, permissions: [] }
    });
    renderRoute("/spaces/personal/chat?session_id=private-session");
    expect(
      screen.getByRole("heading", { name: "Du har inte åtkomst till den personliga chatten" })
    ).toBeTruthy();
    expect(api.GET).not.toHaveBeenCalled();
    expect(screen.queryByRole("textbox")).toBeNull();
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

  it("puts the personal chat's Skills beside the tools in the composer", async () => {
    Object.assign(route.space, personalSpace);
    renderRoute("/spaces/personal/chat", ["personal_chat", "personal_skills"]);

    const skills = await screen.findByRole("button", { name: /^Skills/ });
    const composer = screen
      .getByRole("textbox", { name: "Fråga Personlig assistent" })
      .closest("[data-clear-of-toasts]") as HTMLElement;
    expect(within(composer).getByRole("button", { name: /^Skills/ })).toBe(skills);
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
