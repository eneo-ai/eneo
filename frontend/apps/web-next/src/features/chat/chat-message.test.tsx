// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { EneoUIMessage } from "@/lib/chat/types";
import { expectNoAxeViolations } from "@/test/axe";
import { ChatMessage, PendingAnswer } from "./chat-message";
import { ChatTestProviders, installDomPolyfills } from "./testing";

type Part = EneoUIMessage["parts"][number];

beforeAll(() => installDomPolyfills());
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
  return render(<ChatTestProviders>{ui}</ChatTestProviders>);
}

describe("ChatMessage", () => {
  it("identifies the user's question and shows its attachment as a file token", () => {
    renderMessages(<ChatMessage message={question} assistant={assistant} />);
    const article = screen.getByRole("article", { name: "Ditt meddelande" });
    expect(within(article).getByText("Jämför policyn mot LOU.")).toBeTruthy();
    const file = within(article).getByRole("button", { name: /Upphandlingspolicy 2024\.pdf/ });
    expect(file.textContent).toContain("184.0 kB");
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

  it("offers copy and more actions; thumbs only for the latest answer", () => {
    const onChange = vi.fn();
    const { rerender } = renderMessages(<ChatMessage message={answer} assistant={assistant} />);
    expect(screen.getByRole("button", { name: "Kopiera svaret" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Fler åtgärder" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Bra svar" })).toBeNull();

    rerender(
      <ChatTestProviders>
        <ChatMessage
          message={answer}
          assistant={assistant}
          feedback={{ value: 1, pending: false, onChange }}
        />
      </ChatTestProviders>
    );
    const good = screen.getByRole("button", { name: "Bra svar" });
    expect(good.getAttribute("aria-pressed")).toBe("true");
    const bad = screen.getByRole("button", { name: "Dåligt svar" });
    expect(bad.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(bad);
    expect(onChange).toHaveBeenCalledWith(-1);
  });

  it("shows skeleton lines, not actions, while an answer streams", () => {
    const streaming: EneoUIMessage = { id: "a-2", role: "assistant", parts: [] };
    const { container } = renderMessages(
      <ChatMessage message={streaming} assistant={assistant} isStreaming />
    );
    expect(container.querySelector('[aria-hidden="true"] .animate-pulse')).not.toBeNull();
    expect(screen.queryByRole("button", { name: "Kopiera svaret" })).toBeNull();
  });

  it("has no axe violations for a question, an answer and a pending answer", async () => {
    const { container } = renderMessages(
      <div role="log" aria-label="Konversation">
        <ChatMessage message={question} assistant={assistant} />
        <ChatMessage
          message={answer}
          assistant={assistant}
          feedback={{ value: null, pending: false, onChange: vi.fn() }}
        />
        <PendingAnswer assistant={assistant} />
      </div>
    );
    await expectNoAxeViolations(container);
  });
});
