import type { ConversationMessage, InfoBlob } from "@eneo/eneo-js";
import { page } from "vitest/browser";
import { render } from "vitest-browser-svelte";
import { describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";

const scene = vi.hoisted(() => ({
  partner: {} as Record<string, unknown>,
  message: {} as Record<string, unknown>,
  isLoading: false,
  isLast: true
}));

vi.mock("$lib/core/AppContext", () => ({ getAppContext: () => ({ settings: {} }) }));
vi.mock("$lib/features/chat/ChatService.svelte", () => ({
  getChatService: () => ({ partner: scene.partner })
}));
// Each render snapshots the scene, so two messages can share one page.
vi.mock("$lib/features/chat/MessageContext.svelte", () => ({
  getMessageContext: () => {
    const { message, isLast, isLoading } = scene;
    return {
      current: () => message as unknown as ConversationMessage,
      isLast: () => isLast,
      isLoading: () => isLoading
    };
  }
}));
vi.mock("$lib/features/knowledge/FaviconUrlService.svelte", () => ({
  getFaviconUrlService: () => ({ getFavicon: () => "" })
}));
vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    infoBlobs: {
      get: async (blob: InfoBlob) => ({ ...blob, text: "Dokumentets text" })
    }
  })
}));

import MessageTools from "./MessageTools.svelte";

function reference(id: string, title: string, url: string | null): InfoBlob {
  return { id, metadata: { url, title }, source_metadata: [] } as unknown as InfoBlob;
}

function show({
  partner,
  references = [],
  isLoading = false,
  isLast = true
}: {
  partner: Record<string, unknown>;
  references?: InfoBlob[];
  isLoading?: boolean;
  isLast?: boolean;
}) {
  scene.partner = partner;
  scene.message = { answer: "Svar.", references, mcp_tool_references: [] };
  scene.isLoading = isLoading;
  scene.isLast = isLast;
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

  it("keeps an earlier message's notice while a newer reply streams", async () => {
    show({ partner: injectAssistant, isLoading: true, isLast: false });
    show({ partner: injectAssistant, isLoading: true, isLast: true });

    await expect.element(page.getByRole("status")).toHaveTextContent(m.chat_no_sources_found());
    expect(page.getByText(m.chat_no_sources_found()).elements()).toHaveLength(1);
  });

  it("shows the references toggle instead when the reply cites sources", async () => {
    show({
      partner: injectAssistant,
      references: [reference("ref-1", "Doc", "https://example.test")]
    });
    await expect
      .element(page.getByRole("button", { name: new RegExp(m.references()) }))
      .toBeVisible();
    expect(page.getByText(m.chat_no_sources_found()).query()).toBeNull();
  });
});

describe("MessageTools references", () => {
  it("links a reference only to a stored http(s) address and previews the rest", async () => {
    show({
      partner: injectAssistant,
      references: [
        reference("a", "Riktlinje", "https://kommun.se/riktlinje"),
        reference("b", "Planterad", "javascript:alert(document.cookie)")
      ]
    });

    await page.getByRole("button", { name: new RegExp(m.references()) }).click();

    await expect
      .element(page.getByRole("link", { name: /Riktlinje/ }))
      .toHaveAttribute("href", "https://kommun.se/riktlinje");
    expect(page.getByRole("link", { name: /Planterad/ }).elements()).toHaveLength(0);
    expect(document.body.innerHTML.toLowerCase()).not.toContain("javascript:");

    // The unsafe one opens the document's preview instead.
    await page.getByRole("button", { name: /Planterad/ }).click();
    await expect
      .element(page.getByRole("dialog", { name: "Planterad" }).getByText("Dokumentets text"))
      .toBeVisible();
  });
});
