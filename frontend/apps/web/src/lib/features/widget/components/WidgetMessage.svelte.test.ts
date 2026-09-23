import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, test, vi } from "vitest";
import type { ConversationMessage } from "@eneo/eneo-js";
import "../../../../app.css";
import axe from "axe-core";
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

function renderMessage(answer = "Svaret.", showSources = true) {
  return render(WidgetMessage, {
    message: message(answer),
    index: 0,
    isLast: true,
    isLoading: false,
    showSources
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
      `Taxa plan- och bygglov.pdf – ${location.origin}/documents/${FILE_ID}`
    );
    await expect.element(page.getByText("widget_reference_copied").first()).toBeVisible();
  });

  test("shows the reference as text when the clipboard is unavailable", async () => {
    vi.spyOn(navigator.clipboard, "writeText").mockRejectedValue(new Error("denied"));
    renderMessage();

    await page.getByRole("button", { name: /widget_sources_count_other/ }).click();
    await page.getByRole("button", { name: /widget_copy_reference_for/ }).click();

    await expect.element(page.getByText(`/documents/${FILE_ID}`, { exact: false })).toBeVisible();
  });

  test("hides citations and the list when the widget does not show sources", async () => {
    renderMessage(`Bygglov kostar pengar <inref id="${FILE_ID.slice(0, 8)}"/>.`, false);

    await expect.element(page.getByText("Bygglov kostar pengar", { exact: false })).toBeVisible();
    expect(page.getByRole("button", { name: /widget_sources_count/ }).elements()).toHaveLength(0);
    expect(page.getByRole("link", { name: /widget_citation_label/ }).elements()).toHaveLength(0);
  });

  test("folds finished tool activity into one line that opens to a timeline", async () => {
    const call = (id: string, timezone: string) => ({
      server_name: "TimeMCP",
      tool_name: "get_current_time",
      arguments: { timezone },
      tool_call_id: id,
      result_status: "completed"
    });
    render(WidgetMessage, {
      message: {
        ...message("Klockan är 14:02."),
        tool_calls: [call("c1", "Europe/Stockholm"), call("c2", "Asia/Tokyo")]
      } as unknown as ConversationMessage,
      index: 0,
      isLast: true,
      isLoading: false
    });

    const summary = page.getByRole("button", { name: /Get current time/ });
    await expect.element(summary).toHaveAttribute("aria-expanded", "false");
    await expect.element(summary).toHaveTextContent("internal_tool_steps_count");
    expect(page.getByText("Asia/Tokyo").elements()).toHaveLength(0);
    expect(page.getByText("get_current_time").elements()).toHaveLength(0);

    await summary.click();

    await expect.element(page.getByText("Europe/Stockholm")).toBeVisible();
    await expect.element(page.getByText("Asia/Tokyo")).toBeVisible();
    await expect.element(page.getByText(/widget_activity_via/)).toHaveTextContent("TimeMCP");
  });

  test("shows only the latest step while the assistant is still working", async () => {
    render(WidgetMessage, {
      message: {
        ...message(""),
        mcp_tool_calls: [
          {
            server_name: "TimeMCP",
            tool_name: "get_current_time",
            arguments: { timezone: "UTC" },
            tool_call_id: "c1",
            result_status: "completed"
          },
          {
            server_name: "TimeMCP",
            tool_name: "convert_time",
            arguments: { timezone: "Asia/Tokyo" },
            tool_call_id: "c2",
            result_status: "pending"
          }
        ]
      } as unknown as ConversationMessage,
      index: 0,
      isLast: true,
      isLoading: true
    });

    await expect.element(page.getByText("Convert time: Asia/Tokyo…")).toBeVisible();
    expect(page.getByText("UTC").elements()).toHaveLength(0);
    expect(page.getByRole("button", { name: /internal_tool_steps_count/ }).elements()).toHaveLength(
      0
    );
  });

  test("citations, the open source list and tool activity pass axe", async () => {
    render(WidgetMessage, {
      message: {
        ...message(`Bygglov kostar pengar <inref id="${FILE_ID.slice(0, 8)}"/>.`),
        tool_calls: [
          {
            server_name: "TimeMCP",
            tool_name: "get_current_time",
            arguments: { timezone: "Europe/Stockholm" },
            tool_call_id: "c1",
            result_status: "completed"
          },
          {
            server_name: "TimeMCP",
            tool_name: "get_current_time",
            arguments: { timezone: "Asia/Tokyo" },
            tool_call_id: "c2",
            result_status: "completed"
          }
        ]
      } as unknown as ConversationMessage,
      index: 0,
      isLast: true,
      isLoading: false
    });
    await page.getByRole("button", { name: /widget_sources_count_other/ }).click();
    await page.getByRole("button", { name: /Get current time/ }).click();
    await expect.element(page.getByText("Asia/Tokyo")).toBeVisible();

    // A lone list item outside a page: the page-level rules (landmarks, h1,
    // list parent) are covered by the chat's axe test; this checks the
    // message's own markup.
    const result = await axe.run(document, {
      rules: {
        "color-contrast": { enabled: false },
        "landmark-one-main": { enabled: false },
        "page-has-heading-one": { enabled: false },
        region: { enabled: false },
        listitem: { enabled: false }
      }
    });
    expect(
      JSON.stringify(
        result.violations.map((v) => ({
          id: v.id,
          targets: v.nodes.map((n) => n.target.join(" "))
        }))
      )
    ).toBe("[]");
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
