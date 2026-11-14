// @vitest-environment jsdom
import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderInApp } from "@/test/render";
import type { WidgetMessage as Message } from "./use-widget-conversation";
import { WidgetMessage } from "./widget-message";

function reference(id: string, title: string, url: string | null) {
  return {
    id,
    metadata: { title, url, embedding_model_id: "em", size: 10 },
    group_id: null,
    website_id: null,
    original_available: true
  };
}

function message(references: ReturnType<typeof reference>[]): Message {
  return {
    id: "message-1",
    question: "Vad kostar bygglov?",
    answer: "Svaret.",
    references,
    files: [],
    generated_files: [],
    tools: { assistants: [] },
    mcp_tool_references: [],
    completion_model: null
  } as unknown as Message;
}

describe("WidgetMessage source links", () => {
  it("a knowledge source links out only to an absolute web address", () => {
    renderInApp(
      <ol>
        <WidgetMessage
          message={message([
            reference(
              "aaaaaaaa-0000-4000-8000-000000000001",
              "Webbsida",
              "https://sundsvall.se/bygglov"
            ),
            reference("cccccccc-0000-4000-8000-000000000003", "Skript", "javascript:alert(1)"),
            reference("dddddddd-0000-4000-8000-000000000004", "E-post", "mailto:x@example.com"),
            reference("eeeeeeee-0000-4000-8000-000000000005", "Relativ", "/intern/sida"),
            reference("ffffffff-0000-4000-8000-000000000006", "Protokollrelativ", "//evil.example")
          ])}
          index={0}
          isLast
          isLoading={false}
        />
      </ol>
    );
    fireEvent.click(screen.getByRole("button", { name: /5 källor/ }));
    const sources = screen.getByRole("region", { name: "Källor" });
    expect(
      within(sources)
        .getAllByRole("link")
        .map((link) => link.getAttribute("href"))
    ).toEqual(["https://sundsvall.se/bygglov"]);
    // The other sources are listed, as documents without a link.
    for (const title of ["Skript", "E-post", "Relativ", "Protokollrelativ"]) {
      expect(within(sources).getByText(title)).toBeTruthy();
    }
  });
});
