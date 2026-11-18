// @vitest-environment jsdom
import { cleanup } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp, testQueryClient } from "@/test/render";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import type { Space } from "@/features/spaces/space";
import { AssistantEditor } from "./assistant-editor";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  return { useSpace: () => useSpaceFromQuery(() => state.space) };
});
const state = vi.hoisted(() => ({ space: null as unknown as Space }));
vi.mock("@/features/skills/use-can-attach-skills", () => ({ useCanAttachSkills: () => false }));
vi.mock("@/features/api-keys/resource-api-keys-section", () => ({
  ResourceApiKeysSection: () => null
}));
vi.mock("./use-assistant-ai-draft", () => ({
  useAssistantAiDraft: () => ({ effectiveModel: null, confirmed: true, toolModel: null })
}));
vi.mock("./general-section", () => ({ GeneralSection: () => null }));
vi.mock("./instructions-section", () => ({ InstructionsSection: () => null }));
vi.mock("./knowledge-section", () => ({ KnowledgeSection: () => null }));
vi.mock("./mcp-section", () => ({ McpSection: () => null }));
vi.mock("./ai-section", () => ({ AiSection: () => null }));
vi.mock("./capabilities-section", () => ({
  CapabilitiesSection: () => null,
  selectedCapabilities: () => []
}));
vi.mock("./attachments-section", () => ({ AttachmentsSection: () => null }));
vi.mock("./security-section", () => ({ SecuritySection: () => null }));
vi.mock("./publishing-section", () => ({ PublishingSection: () => null }));
afterEach(cleanup);

it("lists its sections on a phone's index under the same groups as the app editor", () => {
  state.space = makeSpace();
  const queryClient = testQueryClient();
  queryClient.setQueryData(["assistants", "assistant-1"], {
    id: "assistant-1",
    name: "Bygglov",
    permissions: ["read", "edit", "publish"],
    groups: [],
    websites: [],
    integration_knowledge_list: [],
    mcp_servers: [],
    attachments: [],
    prompt: null,
    completion_model: null
  });
  renderInApp(<AssistantEditor assistantId="assistant-1" />, {
    queryClient,
    route: "/spaces/space-1/assistants/assistant-1/edit"
  });

  const groups = [...document.querySelectorAll("[data-editor-index] > div")].map((group) => [
    group.querySelector("h2")?.textContent,
    [...group.querySelectorAll("[data-editor-row]")].map((row) =>
      row.getAttribute("data-editor-row")
    )
  ]);
  expect(groups).toEqual([
    ["Innehåll", ["general", "instructions", "knowledge", "mcp", "attachments"]],
    ["Modell och funktioner", ["ai", "capabilities"]],
    ["Åtkomst", ["security", "api-keys", "widget", "publishing"]]
  ]);
});
