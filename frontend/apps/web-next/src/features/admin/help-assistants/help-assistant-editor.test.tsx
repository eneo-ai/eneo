// @vitest-environment jsdom
import { act, cleanup, screen } from "@testing-library/react";
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
    supports_tool_calling: true
  }))
);
vi.mock("@/features/spaces/use-space", () => ({
  useSpace: () => ({
    routeId: "organization",
    space: { completion_models: models },
    can: () => true
  })
}));
const api = vi.hoisted(() => ({ POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
afterEach(() => {
  cleanup();
  api.POST.mockReset();
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
