// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { queuePartnerUpdate } from "@/features/chat/partner-updates";
import { makeQueryClient } from "@/lib/api/query";
import { renderInApp, testAppContext, testQueryClient } from "@/test/render";
import { SpaceChat } from "@/features/spaces/chat/space-chat.client";

const route = vi.hoisted(() => ({
  unavailableModel: false,
  lockedModel: false,
  /** A second model to switch to, beside the assistant's own. */
  otherModel: false,
  space: {
    id: "space-1",
    name: "Upphandling",
    personal: false,
    organization: false,
    security_classification: null,
    default_assistant: null as unknown,
    completion_models: []
  },
  /** The conversation detail GET answers with a saved conversation. */
  savedSession: false
}));
const forbidden = vi.hoisted(
  () => async (path: string, init?: { params?: { path?: { session_id?: string } } }) => {
    if (path === "/api/v1/conversations/{session_id}/" && route.savedSession)
      return {
        data: {
          id: init?.params?.path?.session_id,
          name: "Samtal om gränser",
          feedback: null,
          messages: [
            {
              id: "m-1",
              question: "Vilken gräns gäller?",
              answer: "Gränsen är 700 000 kr.",
              references: [],
              files: [],
              generated_files: [],
              tools: { assistants: [] },
              feedback: null
            }
          ]
        },
        response: new Response()
      };
    return {
      data: undefined,
      error: { message: "Forbidden" },
      response: new Response(null, { status: 403 })
    };
  }
);
const answer = vi.hoisted(
  () => async (path: string, init?: { body?: unknown; signal?: AbortSignal }) => ({
    data: path.includes("settings/resolve")
      ? {
          revision: (init?.body as { session_id?: string })?.session_id ? 1 : 0,
          settings: {
            completion_model_id: route.unavailableModel ? "removed" : "model-1",
            ...(init?.body as { settings?: object })?.settings
          },
          reasoning_effort_options: (
            route.space.default_assistant as typeof personalSpace.default_assistant | null
          )?.effective_config.reasoning_effort_user_configurable
            ? ["low", "medium", "high"]
            : [],
          default_reasoning_effort: "medium",
          available_models: route.otherModel ? [reasoningModel, otherModel] : [reasoningModel],
          effective_model:
            (init?.body as { settings?: { completion_model_id?: string } })?.settings
              ?.completion_model_id === "model-2"
              ? otherModel
              : reasoningModel,
          model_unavailable: route.unavailableModel,
          model_locked: route.lockedModel
        }
      : init?.body,
    response: new Response()
  })
);
const api = vi.hoisted(() => ({
  GET: vi.fn(),
  PATCH: vi.fn(async (_path: string, init: { body: { settings: object } }) => ({
    data: { revision: 2, settings: init.body.settings },
    response: new Response()
  })),
  POST: vi.fn(answer)
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
const otherModel = {
  id: "model-2",
  name: "claude-sonnet",
  nickname: "Claude Sonnet",
  org: "Anthropic",
  max_input_tokens: 200000,
  reasoning: false
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
  localStorage.clear();
  api.GET.mockImplementation(forbidden);
});

afterEach(() => {
  cleanup();
  api.GET.mockClear();
  api.POST.mockReset();
  api.POST.mockImplementation(answer);
  api.PATCH.mockClear();
  route.unavailableModel = false;
  route.lockedModel = false;
  route.otherModel = false;
  route.savedSession = false;
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
  it("keeps the picker usable when the saved model is unavailable and only one replacement remains", async () => {
    Object.assign(route.space, personalSpace);
    route.unavailableModel = true;
    renderRoute("/spaces/personal/chat");
    await screen.findByText("Den sparade modellen är inte tillgänglig");
    const picker = await screen.findByRole("button", { name: /^Chattmodell:/ });
    fireEvent.click(picker);
    const option = await screen.findByRole("option", { name: /GPT-5/ });
    route.unavailableModel = false;
    fireEvent.click(option);
    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/conversations/settings/resolve/", {
        body: {
          assistant_id: "assistant-1",
          settings: { completion_model_id: "model-1", reasoning_effort: null }
        }
      })
    );
    await waitFor(() =>
      expect(screen.queryByText("Den sparade modellen är inte tillgänglig")).toBeNull()
    );
  });

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
    expect(await screen.findByRole("radio", { name: "Insikter" })).toBeTruthy();
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
      if (path === "/api/v1/conversations/settings/resolve/") return answer(path, init);
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

  it("lets the personal assistant's reasoning effort be picked beside the model and keeps it in the conversation draft", async () => {
    Object.assign(route.space, personalSpace);
    renderRoute("/spaces/personal/chat");

    const effort = await screen.findByRole("combobox", { name: "Resonemangsnivå: Medel" });
    // Beside the model picker, in the composer's send actions.
    expect(screen.getByRole("button", { name: /^Chattmodell: GPT-5/ })).toBeTruthy();
    fireEvent.click(effort);
    fireEvent.click(await screen.findByRole("option", { name: "Hög" }));

    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/conversations/settings/resolve/", {
        body: {
          assistant_id: "assistant-1",
          settings: { completion_model_id: "model-1", reasoning_effort: "high" }
        }
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

  it("shows the model the policy pins as a read-only field instead of a picker", async () => {
    Object.assign(route.space, personalSpace);
    route.lockedModel = true;
    renderRoute("/spaces/personal/chat");
    const field = await screen.findByRole("combobox", { name: "Chattmodell" });
    expect(field.getAttribute("aria-readonly")).toBe("true");
    expect(field.textContent).toContain("GPT-5");
    const description = field
      .getAttribute("aria-describedby")!
      .split(" ")
      .map((id) => document.getElementById(id)?.textContent)
      .join(" ");
    expect(description).toContain("Låst av administratör");
    expect(screen.queryByRole("button", { name: /^Chattmodell:/ })).toBeNull();
  });

  it("starts a new conversation with the picked model from the model-change dialog", async () => {
    Object.assign(route.space, personalSpace);
    route.otherModel = true;
    route.savedSession = true;
    window.history.replaceState(null, "", "/spaces/space-1/chat?session_id=s-1");
    renderRoute("/spaces/personal/chat?session_id=s-1");
    const log = await screen.findByRole("log", { name: "Konversation" });
    expect(within(log).getByText("Gränsen är 700 000 kr.")).toBeTruthy();

    fireEvent.click(await screen.findByRole("button", { name: /^Chattmodell: GPT-5/ }));
    fireEvent.click(await screen.findByRole("option", { name: /Claude Sonnet/ }));
    const dialog = await screen.findByRole("dialog", {
      name: "Byta modell i den här konversationen?"
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Starta ny konversation" }));

    await waitFor(() => expect(log.isConnected).toBe(false));
    expect(window.location.pathname + window.location.search).toBe("/spaces/space-1/chat");
    // The saved conversation keeps its model; the draft starts with the picked one.
    expect(api.PATCH).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/conversations/settings/resolve/", {
        body: {
          assistant_id: "assistant-1",
          settings: expect.objectContaining({
            completion_model_id: "model-2",
            reasoning_effort: null
          })
        }
      })
    );
    expect(await screen.findByRole("button", { name: /^Chattmodell: Claude Sonnet/ })).toBeTruthy();
    await waitFor(() =>
      expect(document.activeElement).toBe(
        screen.getByRole("textbox", { name: "Fråga Personlig assistent" })
      )
    );
  });

  it("holds the model and reasoning still while a question waits for a Skills save", async () => {
    Object.assign(route.space, personalSpace);
    renderRoute("/spaces/personal/chat");
    await screen.findByRole("combobox", { name: "Resonemangsnivå: Medel" });
    // Read anew: the waiting question takes the view from the start state to the conversation.
    const held = () => [
      screen.getByRole("button", { name: /^Chattmodell: GPT-5/ }).getAttribute("aria-disabled") ===
        "true",
      screen.getByRole("combobox", { name: "Resonemangsnivå: Medel" }).closest("fieldset")!.disabled
    ];
    expect(held()).toEqual([false, false]);
    let saved!: () => void;
    void queuePartnerUpdate(() => new Promise<void>((resolve) => (saved = resolve)));

    fireEvent.change(screen.getByRole("textbox", { name: "Fråga Personlig assistent" }), {
      target: { value: "Skicka när Skills är sparade" }
    });
    fireEvent.click(screen.getByRole("button", { name: "Skicka meddelande" }));

    // The waiting question already carries the conversation's settings revision.
    expect(held()).toEqual([true, true]);
    await act(async () => {
      await Promise.resolve();
      saved();
    });
  });

  it("keeps the next conversation's model when leaving an unsent question is cancelled", async () => {
    Object.assign(route.space, personalSpace);
    route.otherModel = true;
    route.savedSession = true;
    window.history.replaceState(null, "", "/spaces/space-1/chat?session_id=s-1");
    renderRoute("/spaces/personal/chat?session_id=s-1");
    const log = await screen.findByRole("log", { name: "Konversation" });
    fireEvent.change(screen.getByRole("textbox", { name: "Fråga Personlig assistent" }), {
      target: { value: "Unsent follow-up" }
    });

    fireEvent.click(await screen.findByRole("button", { name: /^Chattmodell: GPT-5/ }));
    fireEvent.click(await screen.findByRole("option", { name: /Claude Sonnet/ }));
    const dialog = await screen.findByRole("dialog", {
      name: "Byta modell i den här konversationen?"
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Starta ny konversation" }));
    const leave = await screen.findByRole("alertdialog", { name: "Lämna chatten?" });
    fireEvent.click(within(leave).getByRole("button", { name: "Avbryt" }));

    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(log.isConnected).toBe(true);
    // Focus goes back to the picker the change started from (WCAG 2.4.3).
    await waitFor(() =>
      expect(document.activeElement).toBe(
        screen.getByRole("button", { name: /^Chattmodell: GPT-5/ })
      )
    );
    const stored = Array.from({ length: localStorage.length }, (_, index) =>
      localStorage.getItem(localStorage.key(index)!)
    ).join();
    expect(stored).not.toContain("model-2");
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
