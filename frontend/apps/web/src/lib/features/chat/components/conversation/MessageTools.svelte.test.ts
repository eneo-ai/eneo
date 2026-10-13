import type { ConversationMessage } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";

const scene = vi.hoisted(() => ({
  partner: {} as Record<string, unknown>,
  message: {} as Record<string, unknown>,
  isLoading: false
}));

vi.mock("$lib/core/AppContext", () => ({ getAppContext: () => ({ settings: {} }) }));
vi.mock("$lib/features/chat/ChatService.svelte", () => ({
  getChatService: () => ({ partner: scene.partner })
}));
vi.mock("$lib/features/chat/MessageContext.svelte", () => ({
  getMessageContext: () => ({
    current: () => scene.message as unknown as ConversationMessage,
    isLast: () => true,
    isLoading: () => scene.isLoading
  })
}));
vi.mock("$lib/features/knowledge/FaviconUrlService.svelte", () => ({
  getFaviconUrlService: () => ({ getFavicon: () => "" })
}));

import MessageTools from "./MessageTools.svelte";

function show({
  partner,
  references = [],
  isLoading = false
}: {
  partner: Record<string, unknown>;
  references?: Array<{ id: string; metadata: { url?: string; title?: string } }>;
  isLoading?: boolean;
}) {
  scene.partner = partner;
  scene.message = { answer: "Svar.", references, mcp_tool_references: [] };
  scene.isLoading = isLoading;
  return render(MessageTools);
}

const injectAssistant = {
  type: "assistant",
  knowledge_mode: "inject",
  integration_knowledge_list: [{ id: "i1", name: "Intranet" }],
  groups: [],
  websites: [],
  completion_model: { id: "m", supports_tool_calling: true }
};

describe("MessageTools knowledge notice", () => {
  it("says no sources were found when inject-mode knowledge yielded no references", async () => {
    show({ partner: injectAssistant });
    await expect.element(page.getByRole("status")).toHaveTextContent(m.chat_no_sources_found());
    expect(page.getByRole("button", { name: new RegExp(m.references()) }).query()).toBeNull();
  });

  it.each([
    ["the reply still streams", { partner: injectAssistant, isLoading: true }],
    [
      "the assistant has no knowledge",
      { partner: { ...injectAssistant, integration_knowledge_list: [] } }
    ],
    ["knowledge runs in tool mode", { partner: { ...injectAssistant, knowledge_mode: "tool" } }]
  ] as const)("stays silent while %s", async (_label, options) => {
    show(options);
    expect(page.getByText(m.chat_no_sources_found()).query()).toBeNull();
  });

  it("shows the references toggle instead when the reply cites sources", async () => {
    show({
      partner: injectAssistant,
      references: [{ id: "ref-1", metadata: { url: "https://example.test", title: "Doc" } }]
    });
    await expect
      .element(page.getByRole("button", { name: new RegExp(m.references()) }))
      .toBeVisible();
    expect(page.getByText(m.chat_no_sources_found()).query()).toBeNull();
  });
});
