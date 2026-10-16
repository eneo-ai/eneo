import type { InfoBlob } from "@eneo/eneo-js";
import { page } from "vitest/browser";
import { render } from "vitest-browser-svelte";
import { expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";

const message = vi.hoisted(() => ({ references: [] as unknown[] }));

vi.mock("$lib/core/AppContext", () => ({ getAppContext: () => ({ settings: {} }) }));
vi.mock("../../MessageContext.svelte", () => ({
  getMessageContext: () => ({
    current: () => ({
      answer: "",
      references: message.references,
      mcp_tool_references: []
    }),
    isLast: () => true
  })
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

it("links a reference only to a stored http(s) address and previews the rest", async () => {
  message.references = [
    reference("a", "Riktlinje", "https://kommun.se/riktlinje"),
    reference("b", "Planterad", "javascript:alert(document.cookie)")
  ];
  render(MessageTools);

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
