// A conversation whose name retention emptied is shown as untitled, in each language.
import type { ConversationSparse } from "@eneo/eneo-js";
import { page } from "vitest/browser";
import { render } from "vitest-browser-svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import { getLocale, overwriteGetLocale } from "$lib/paraglide/runtime";
import InsightsConversationPrimaryCell from "./InsightsConversationPrimaryCell.svelte";

vi.mock("../InsightsService.svelte", () => ({
  getInsightsService: () => ({ previewedConversation: null, loadConversationPreview: vi.fn() })
}));

const resolveLocale = getLocale;

afterEach(() => {
  overwriteGetLocale(resolveLocale);
});

describe("InsightsConversationPrimaryCell", () => {
  it.each([
    ["sv", "Namnlös"],
    ["en", "Untitled"]
  ] as const)("shows a conversation without a name as untitled in %s", async (locale, untitled) => {
    overwriteGetLocale(() => locale);
    const conversation = {
      id: "conversation",
      name: "",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z"
    } as ConversationSparse;

    render(InsightsConversationPrimaryCell, { conversation });

    await expect.element(page.getByRole("button", { name: untitled })).toBeVisible();
  });
});
