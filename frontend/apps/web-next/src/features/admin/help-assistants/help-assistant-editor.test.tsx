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
afterEach(cleanup);
it("renders the real shared AI section and adopts external model changes in the helper editor", async () => {
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
