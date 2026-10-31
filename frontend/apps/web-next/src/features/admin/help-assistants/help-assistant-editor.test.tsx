// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp, testQueryClient } from "@/test/render";
import type { Assistant } from "@/features/assistants/editor/use-assistant";
import { HelpAssistantEditor } from "./help-assistant-editor";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/features/assistants/editor/general-section", () => ({ GeneralSection: () => null }));
vi.mock("@/features/assistants/editor/security-section", () => ({ SecuritySection: () => null }));
const models = vi.hoisted(() =>
  ["A", "B"].map((name) => ({
    id: name,
    name: `Model ${name}`,
    nickname: `Model ${name}`,
    token_limit: 1000,
    max_input_tokens: 1000,
    supports_tool_calling: true,
    supported_model_kwargs: { temperature: { supported: name !== "A" }, top_p: { supported: true } }
  }))
);
vi.mock("@/features/spaces/use-space", () => ({
  useSpace: () => ({
    routeId: "organization",
    space: { completion_models: models },
    can: () => true
  })
}));
const api = vi.hoisted(() => ({ POST: vi.fn(), GET: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
afterEach(() => {
  cleanup();
  api.POST.mockReset();
  api.GET.mockReset();
});
it("renders the real shared AI section and adopts external model changes in the helper editor", async () => {
  api.POST.mockResolvedValue({
    data: { file_tokens: 0, prompt_tokens: 0 },
    response: new Response("{}")
  });
  const queryClient = testQueryClient();
  const assistant = {
    id: "helper",
    name: "Prompt guide",
    completion_model: models[0],
    completion_model_kwargs: {},
    prompt: { text: "" },
    attachments: []
  } as unknown as Assistant;
  queryClient.setQueryData(["assistants", "helper"], assistant);
  renderInApp(<HelpAssistantEditor assistantId="helper" helperKind="prompt_guide" />, {
    queryClient
  });
  expect(screen.getByRole("button", { name: /Model A/ })).toBeTruthy();
  expect(
    (screen.getByRole("combobox", { name: "Modellbeteende" }) as HTMLButtonElement).disabled
  ).toBe(true);
  act(() =>
    queryClient.setQueryData(["assistants", "helper"], {
      ...assistant,
      completion_model: models[1]
    })
  );
  expect(await screen.findByRole("button", { name: /Model B/ })).toBeTruthy();
});

it("leaves governed instructions to the server baseline instead of overriding with stored text", async () => {
  api.POST.mockResolvedValue({
    data: {
      file_tokens: 0,
      prompt_tokens: 700,
      skill_context_tokens: 300,
      context_reserve_tokens: 0
    },
    response: new Response("{}")
  });
  const queryClient = testQueryClient();
  queryClient.setQueryData(["assistants", "helper"], {
    id: "helper",
    name: "Governed helper",
    completion_model: models[0],
    completion_model_kwargs: {},
    prompt: { text: "Short stored prompt" },
    attachments: [],
    effective_config: { prompt_locked: true, available_models: [] }
  } as unknown as Assistant);
  renderInApp(<HelpAssistantEditor assistantId="helper" helperKind="prompt_guide" />, {
    queryClient
  });
  expect(await screen.findByRole("button", { name: /Kontextbudget: ~700/ })).toBeTruthy();
  expect(api.POST).toHaveBeenCalledWith(
    "/api/v1/conversations/preflight",
    expect.objectContaining({
      body: expect.not.objectContaining({ assistant_prompt: expect.anything() })
    })
  );
  expect((screen.getByRole("textbox", { name: "Prompt" }) as HTMLTextAreaElement).disabled).toBe(
    true
  );
});

it.each([false, true])(
  "records restore provenance through assistant autosave even for identical text: %s",
  async (identical) => {
    const assistant = {
      id: "helper",
      name: "Helper",
      completion_model: models[0],
      completion_model_kwargs: {},
      prompt: { text: identical ? "Old body" : "Current body" },
      attachments: []
    } as unknown as Assistant;
    const old = {
      id: "old",
      text: "Old body",
      description: "Historic marker",
      created_at: "2026-10-01T12:00:00Z",
      is_selected: false,
      user: { id: "user-1", email: "owner@example.se" }
    };
    api.GET.mockImplementation(async (path) => ({
      data: path.includes("/prompts/{id}") ? old : { items: [old] },
      response: new Response("{}")
    }));
    api.POST.mockImplementation(async (path, init) => ({
      data: path.endsWith("/preflight")
        ? { file_tokens: 0, prompt_tokens: 0 }
        : { ...assistant, prompt: init.body.prompt },
      response: new Response("{}")
    }));
    const queryClient = testQueryClient();
    queryClient.setQueryData(["assistants", "helper"], assistant);
    renderInApp(<HelpAssistantEditor assistantId="helper" helperKind="prompt_guide" />, {
      queryClient
    });
    fireEvent.click(screen.getByRole("button", { name: "Visa prompthistorik" }));
    fireEvent.click(await screen.findByRole("button", { name: /Historic marker/ }));
    await screen.findByRole("button", { name: "Återställ denna version" });
    fireEvent.click(
      screen.getByRole("button", { name: /Återställ denna version|Använd denna version/ })
    );
    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith(
        "/api/v1/assistants/{id}/",
        expect.objectContaining({
          body: {
            prompt: {
              text: "Old body",
              description: expect.stringMatching(/^Återställd prompt från /)
            }
          }
        })
      )
    );
  }
);

it("does not restore old provenance when manual A returns while assistant save B is held", async () => {
  const assistant = {
    id: "helper",
    name: "Helper",
    completion_model: models[0],
    completion_model_kwargs: {},
    prompt: { text: "Original A", description: "Restored original marker" },
    attachments: []
  } as unknown as Assistant;
  let release!: () => void;
  const held = new Promise((resolve) => {
    release = () =>
      resolve({
        data: { ...assistant, prompt: { text: "Manual B", description: "" } },
        response: new Response("{}")
      });
  });
  api.POST.mockImplementation((path, init) => {
    if (path.endsWith("/preflight"))
      return Promise.resolve({
        data: { file_tokens: 0, prompt_tokens: 0 },
        response: new Response("{}")
      });
    if (init.body.prompt.text === "Manual B") return held;
    return Promise.resolve({
      data: { ...assistant, prompt: init.body.prompt },
      response: new Response("{}")
    });
  });
  const queryClient = testQueryClient();
  queryClient.setQueryData(["assistants", "helper"], assistant);
  renderInApp(<HelpAssistantEditor assistantId="helper" helperKind="prompt_guide" />, {
    queryClient
  });
  const field = screen.getByRole("textbox", { name: "Prompt" });
  fireEvent.change(field, { target: { value: "Manual B" } });
  fireEvent.blur(field);
  await waitFor(() =>
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/assistants/{id}/",
      expect.objectContaining({ body: { prompt: { text: "Manual B", description: "" } } })
    )
  );
  try {
    fireEvent.change(field, { target: { value: "Original A" } });
    fireEvent.blur(field);
    release();
    await waitFor(() =>
      expect(
        api.POST.mock.calls.filter(([path]) => path === "/api/v1/assistants/{id}/")
      ).toHaveLength(2)
    );
    const writes = api.POST.mock.calls.filter(([path]) => path === "/api/v1/assistants/{id}/");
    expect(writes[1][1].body).toEqual({ prompt: { text: "Original A", description: "" } });
  } finally {
    release();
  }
});
