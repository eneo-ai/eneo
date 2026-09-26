// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { EneoUIMessage } from "@/lib/chat/types";
import { ChatMessage } from "./chat-message";
import { ChatTestProviders, installDomPolyfills } from "./testing";

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("@/lib/toast", () => ({ toast }));

const clipboard = {
  writeText: vi.fn<(text: string) => Promise<void>>(),
  write: vi.fn<(items: unknown[]) => Promise<void>>()
};

class TestClipboardItem {
  constructor(readonly items: Record<string, Blob>) {}
}

// jsdom's Blob has no text().
function readBlob(blob: Blob): Promise<string> {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.readAsText(blob);
  });
}

const answer: EneoUIMessage = {
  id: "a-1",
  role: "assistant",
  parts: [{ type: "text", text: 'Gränsen är **700 000 kr**<inref id="abcd1234"/>.', state: "done" }]
};

function renderAnswer() {
  render(
    <ChatTestProviders>
      <ChatMessage message={answer} assistant={{ id: "assistant-1", name: "Upphandling" }} />
    </ChatTestProviders>
  );
}

function copyAsRichText() {
  const more = screen.getByRole("button", { name: "Fler åtgärder" });
  fireEvent.click(more);
  const menu = document.getElementById(more.getAttribute("aria-controls") ?? "")!;
  fireEvent.click(within(menu).getByRole("menuitem", { name: "Kopiera som Rich text" }));
}

beforeAll(() => installDomPolyfills());
beforeEach(() => {
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: clipboard });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  clipboard.writeText.mockReset();
  clipboard.write.mockReset();
  toast.success.mockReset();
  toast.error.mockReset();
});

describe("copying an answer", () => {
  it("copies the markdown without source tags and confirms it", async () => {
    clipboard.writeText.mockResolvedValue();
    renderAnswer();

    fireEvent.click(screen.getByRole("button", { name: "Kopiera svaret" }));

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Kopierad!"));
    expect(clipboard.writeText).toHaveBeenCalledWith("Gränsen är **700 000 kr**.");
  });

  it("says so when the browser refuses the clipboard", async () => {
    clipboard.writeText.mockRejectedValue(new DOMException("denied", "NotAllowedError"));
    renderAnswer();

    fireEvent.click(screen.getByRole("button", { name: "Kopiera svaret" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Det gick inte att kopiera. Försök igen eller markera texten och kopiera den."
      )
    );
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("copies rich text as HTML with a plain-text twin", async () => {
    vi.stubGlobal("ClipboardItem", TestClipboardItem);
    clipboard.write.mockResolvedValue();
    renderAnswer();

    copyAsRichText();

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Kopierad!"));
    const [item] = clipboard.write.mock.calls[0]![0] as TestClipboardItem[];
    expect(Object.keys(item!.items)).toEqual(["text/plain", "text/html"]);
    expect(await readBlob(item!.items["text/html"]!)).toContain("<strong>700 000 kr</strong>");
    expect(clipboard.writeText).not.toHaveBeenCalled();
  });

  it("falls back to plain text where the browser cannot copy HTML", async () => {
    clipboard.writeText.mockResolvedValue();
    renderAnswer();

    copyAsRichText();

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Kopierad!"));
    expect(clipboard.writeText).toHaveBeenCalledWith("Gränsen är 700 000 kr.");
  });
});
