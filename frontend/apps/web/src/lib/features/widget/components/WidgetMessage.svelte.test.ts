import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, test, vi } from "vitest";
import type { ConversationMessage } from "@eneo/eneo-js";
import "../../../../app.css";
import WidgetMessage from "./WidgetMessage.svelte";

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, (params?: Record<string, unknown>) => string>>(
    {},
    {
      get: (_target, key) => (params?: Record<string, unknown>) =>
        params ? `${String(key)} ${JSON.stringify(params)}` : String(key)
    }
  )
}));

const WEB_ID = "aaaaaaaa-0000-4000-8000-000000000001";
const FILE_ID = "bbbbbbbb-0000-4000-8000-000000000002";

function reference(id: string, title: string, url: string | null) {
  return {
    id,
    metadata: { title, url, embedding_model_id: "em", size: 10 },
    group_id: null,
    website_id: null,
    original_available: true
  };
}

function message(answer: string): ConversationMessage {
  return {
    id: "message-1",
    question: "Vad kostar bygglov?",
    answer,
    references: [
      reference(WEB_ID, "Avgifter för bygglov", "https://sundsvall.se/bygglov/avgifter"),
      // The same document retrieved twice folds into one source.
      reference(WEB_ID, "Avgifter för bygglov", "https://sundsvall.se/bygglov/avgifter"),
      reference(FILE_ID, "Taxa plan- och bygglov.pdf", null)
    ],
    files: [],
    tools: { assistants: [] },
    completion_model: null
  } as unknown as ConversationMessage;
}

function renderMessage(answer = "Svaret.") {
  return render(WidgetMessage, {
    message: message(answer),
    index: 0,
    isLast: true,
    isLoading: false
  });
}

describe("WidgetMessage sources", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  test("keeps the source list collapsed until the visitor opens it", async () => {
    renderMessage();

    const toggle = page.getByRole("button", { name: /widget_sources_count_other/ });
    await expect.element(toggle).toHaveAttribute("aria-expanded", "false");
    await expect.element(toggle).toHaveTextContent('{"count":2}');
    expect(page.getByRole("list").elements()).toHaveLength(0);

    await toggle.click();

    await expect.element(toggle).toHaveAttribute("aria-expanded", "true");
    const link = page.getByRole("link", { name: /Avgifter för bygglov/ });
    await expect.element(link).toHaveAttribute("href", "https://sundsvall.se/bygglov/avgifter");
    await expect.element(link).toHaveAttribute("target", "_blank");
    await expect.element(page.getByText("sundsvall.se")).toBeVisible();
    await expect.element(page.getByText("widget_source_document")).toBeVisible();
  });

  test("copies a document reference for a source without a link", async () => {
    const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
    renderMessage();

    await page.getByRole("button", { name: /widget_sources_count_other/ }).click();
    await page.getByRole("button", { name: /widget_copy_reference_for/ }).click();

    expect(writeText).toHaveBeenCalledWith(
      `Taxa plan- och bygglov.pdf · widget_source_reference_id: ${FILE_ID}`
    );
    await expect.element(page.getByText("widget_reference_copied").first()).toBeVisible();
  });

  test("shows the reference as text when the clipboard is unavailable", async () => {
    vi.spyOn(navigator.clipboard, "writeText").mockRejectedValue(new Error("denied"));
    renderMessage();

    await page.getByRole("button", { name: /widget_sources_count_other/ }).click();
    await page.getByRole("button", { name: /widget_copy_reference_for/ }).click();

    await expect
      .element(page.getByText(`widget_source_reference_id: ${FILE_ID}`, { exact: false }))
      .toBeVisible();
  });

  test("an inline citation opens the list and focuses its source", async () => {
    renderMessage(`Bygglov kostar pengar <inref id="${FILE_ID.slice(0, 8)}"/>.`);

    const citation = page.getByRole("link", { name: /widget_citation_label/ });
    await expect.element(citation).toHaveTextContent("2");
    expect(page.getByRole("list").elements()).toHaveLength(0);

    await userEvent.click(citation);

    const entry = page.getByText("Taxa plan- och bygglov.pdf");
    await expect.element(entry).toBeVisible();
    expect(document.activeElement?.id).toBe("widget-source-0-1");
  });
});
