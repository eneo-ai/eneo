// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { EneoUIMessage } from "@/lib/chat/types";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { ChatMessage, PendingAnswer } from "./chat-message";

type Part = EneoUIMessage["parts"][number];

afterEach(cleanup);

const assistant = { id: "assistant-1", name: "Upphandlingsassistenten" };

const question: EneoUIMessage = {
  id: "q-1",
  role: "user",
  parts: [{ type: "text", text: "Jämför policyn mot LOU." }],
  metadata: {
    files: [
      {
        id: "file-1",
        name: "Upphandlingspolicy 2024.pdf",
        mimetype: "application/pdf",
        size: 188_416
      } as NonNullable<NonNullable<EneoUIMessage["metadata"]>["files"]>[number]
    ]
  }
};

const answer: EneoUIMessage = {
  id: "a-1",
  role: "assistant",
  metadata: {
    completionModel: { id: "m", name: "claude-haiku", nickname: "Claude Haiku 4.5" },
    createdAt: null
  },
  parts: [
    {
      type: "source-document",
      sourceId: "abcd1234-0000",
      mediaType: "text/plain",
      title: "LOU 19 kap."
    } as Part,
    {
      type: "text",
      text: [
        "## Sammanfattning",
        "",
        'Gränsen stämmer<inref id="abcd1234"/>.',
        "",
        "| Kommun | Avvikelse |",
        "| --- | --- |",
        "| Sundsvall | Hög |"
      ].join("\n"),
      state: "done"
    }
  ]
};

function renderMessages(ui: React.ReactNode) {
  return renderInApp(ui);
}

describe("ChatMessage", () => {
  it("sets answers in the app's sans with a reading line height (the serif voice stays one token away)", () => {
    const { container } = renderMessages(<ChatMessage message={answer} assistant={assistant} />);
    expect(container.querySelector(".font-sans.leading-\\[1\\.7\\]")).toBeTruthy();
    expect(container.querySelector(".font-voice")).toBeNull();
  });

  it("identifies the user's question and shows its attachment as a file token", () => {
    renderMessages(<ChatMessage message={question} assistant={assistant} />);
    const article = screen.getByRole("article", { name: "Ditt meddelande" });
    expect(within(article).getByText("Jämför policyn mot LOU.")).toBeTruthy();
    const file = within(article).getByRole("button", { name: /Upphandlingspolicy 2024\.pdf/ });
    expect(file.textContent).toContain("184 kB");
  });

  it("renders an answer: named by its sender, with model, activity pill, table and citation", () => {
    const onActivityToggle = vi.fn();
    renderMessages(
      <ChatMessage message={answer} assistant={assistant} onActivityToggle={onActivityToggle} />
    );
    const article = screen.getByRole("article", {
      name: /svar från upphandlingsassistenten/i
    });
    expect(within(article).getByText("Claude Haiku 4.5")).toBeTruthy();
    expect(article.querySelector("table")).not.toBeNull();
    expect(within(article).getByRole("heading", { level: 3, name: "Sammanfattning" })).toBeTruthy();

    const citation = within(article).getByRole("button", { name: "Källa 1: LOU 19 kap." });
    fireEvent.click(citation);
    expect(onActivityToggle).toHaveBeenCalledWith(citation, { tab: "sources", source: 0 });

    const pill = within(article).getByRole("button", { name: /aktivitet: .*1 källa/i });
    fireEvent.click(pill);
    expect(onActivityToggle).toHaveBeenLastCalledWith(pill);
  });

  it("numbers only cited MCP excerpts when several share one document title", () => {
    const onActivityToggle = vi.fn();
    const blobId = "11111111-1111-1111-1111-111111111111";
    const references = [0, 1, 2].map((chunk) => ({
      id: `${String(chunk + 1).repeat(8)}-aaaa-4aaa-8aaa-aaaaaaaaaaaa`,
      uri: `eneo://info-blob/${blobId}#chunk-${chunk}`,
      mime_type: "text/plain",
      content: `Excerpt ${chunk}`,
      meta: { title: "kaffe_tips", info_blob_id: blobId }
    }));
    const message: EneoUIMessage = {
      id: "coffee-answer",
      role: "assistant",
      parts: [
        { type: "data-mcp-tool-references", data: { mcp_tool_references: references } },
        {
          type: "text",
          text: 'Smak<inref id="11111111"/>. Rostning<inref id="33333333"/>.',
          state: "done"
        }
      ]
    };

    renderMessages(
      <ChatMessage message={message} assistant={assistant} onActivityToggle={onActivityToggle} />
    );
    const citations = screen.getAllByRole("button", { name: /^Källa [12]: kaffe_tips/ });
    expect(citations.map((citation) => citation.textContent)).toEqual(["1", "2"]);
    expect(citations.map((citation) => citation.getAttribute("aria-label"))).toEqual([
      "Källa 1: kaffe_tips · Utdrag 1",
      "Källa 2: kaffe_tips · Utdrag 3"
    ]);
    expect(screen.getByRole("button", { name: /aktivitet: .*2 källor/i })).toBeTruthy();
    fireEvent.click(citations[1]!);
    expect(onActivityToggle).toHaveBeenCalledWith(citations[1], {
      tab: "sources",
      source: 1
    });
  });

  it("opens the activity from the more menu, even when it is already open", async () => {
    const onActivityToggle = vi.fn();
    renderMessages(
      <ChatMessage
        message={answer}
        assistant={assistant}
        activityExpanded
        onActivityToggle={onActivityToggle}
      />
    );
    const more = screen.getByRole("button", { name: "Fler åtgärder" });
    fireEvent.click(more);
    const menu = document.getElementById(more.getAttribute("aria-controls") ?? "")!;
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Visa aktivitet" }));
    // With a tab the panel opens or switches; without one the pill's toggle would close it.
    expect(onActivityToggle).toHaveBeenCalledWith(more, { tab: "steps" });
  });

  it("offers copy and more actions; thumbs where the answer can be rated", () => {
    const onChange = vi.fn();
    const { rerender } = renderMessages(<ChatMessage message={answer} assistant={assistant} />);
    expect(screen.getByRole("button", { name: "Kopiera svaret" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Fler åtgärder" })).toBeTruthy();
    expect(screen.queryByRole("group", { name: "Betygsätt svaret" })).toBeNull();

    rerender(
      <ChatMessage message={answer} assistant={assistant} feedback={{ value: 1, onChange }} />
    );
    const rating = screen.getByRole("group", { name: "Betygsätt svaret" });
    const good = within(rating).getByRole("button", { name: "Bra svar" });
    expect(good.getAttribute("aria-pressed")).toBe("true");
    const bad = within(rating).getByRole("button", { name: "Dåligt svar" });
    expect(bad.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(bad);
    expect(onChange).toHaveBeenLastCalledWith(-1);
    // Pressing the chosen thumb again clears the rating.
    fireEvent.click(good);
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it("shows skeleton lines, not actions, while an answer streams", () => {
    const streaming: EneoUIMessage = { id: "a-2", role: "assistant", parts: [] };
    const { container } = renderMessages(
      <ChatMessage message={streaming} assistant={assistant} isStreaming />
    );
    expect(container.querySelectorAll('[aria-hidden="true"] .astryx-skeleton')).toHaveLength(3);
    expect(screen.getByText("Assistenten tänker…")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Kopiera svaret" })).toBeNull();
  });

  it("has no axe violations for a question, an answer and a pending answer", async () => {
    const { container } = renderMessages(
      <div role="log" aria-label="Konversation">
        <ChatMessage message={question} assistant={assistant} />
        <ChatMessage
          message={answer}
          assistant={assistant}
          feedback={{ value: -1, onChange: vi.fn() }}
        />
        <PendingAnswer assistant={assistant} />
      </div>
    );
    await expectNoAxeViolations(container);
  });
});

describe("ChatMessage debug action", () => {
  it("offers Felsök in the answer's menu only to viewers who may debug", () => {
    const onActivityToggle = vi.fn();
    const { rerender } = renderMessages(
      <ChatMessage message={answer} assistant={assistant} onActivityToggle={onActivityToggle} />
    );
    fireEvent.click(screen.getByRole("button", { name: "Fler åtgärder" }));
    expect(screen.queryByRole("menuitem", { name: "Felsök" })).toBeNull();
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });

    rerender(
      <ChatMessage
        message={answer}
        assistant={assistant}
        onActivityToggle={onActivityToggle}
        canDebug
      />
    );
    const more = screen.getByRole("button", { name: "Fler åtgärder" });
    fireEvent.click(more);
    fireEvent.click(screen.getByRole("menuitem", { name: "Felsök" }));
    // Opens the panel's Felsök tab; the panel returns focus to the menu button.
    expect(onActivityToggle).toHaveBeenCalledWith(more, { tab: "debug" });
  });
});
