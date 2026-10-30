// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EneoUIMessage } from "@/lib/chat/types";
import { katexStore } from "@/components/ai-elements/math";
import { renderInApp } from "@/test/render";
import { ChatMessage } from "./chat-message";

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("@/lib/toast", () => ({ toast }));

const clipboard = {
  writeText: vi.fn<(text: string) => Promise<void>>(),
  write: vi.fn<(items: unknown[]) => Promise<void>>()
};

class TestClipboardItem {
  constructor(readonly items: Record<string, Blob | Promise<Blob>>) {}
}

// The browser writes once every representation has resolved, and fails the
// write when one rejects.
async function writeItems(items: unknown[]) {
  for (const item of items as TestClipboardItem[]) await Promise.all(Object.values(item.items));
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

function renderAnswer(message = answer) {
  renderInApp(
    <ChatMessage message={message} assistant={{ id: "assistant-1", name: "Upphandling" }} />
  );
}

const mathAnswer: EneoUIMessage = {
  id: "a-2",
  role: "assistant",
  parts: [{ type: "text", text: "Arean är $\\pi r^2$.", state: "done" }]
};

function copyAsRichText() {
  const more = screen.getByRole("button", { name: "Fler åtgärder" });
  fireEvent.click(more);
  const menu = document.getElementById(more.getAttribute("aria-controls") ?? "")!;
  fireEvent.click(within(menu).getByRole("menuitem", { name: "Kopiera som Rich text" }));
}

beforeEach(() => {
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: clipboard });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
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

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Kopierat"));
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
    clipboard.write.mockImplementation(writeItems);
    renderAnswer();

    copyAsRichText();

    // Safari requires this call during the click, before the renderer import settles.
    expect(clipboard.write).toHaveBeenCalledOnce();
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Kopierat"));
    const [item] = clipboard.write.mock.calls[0]![0] as TestClipboardItem[];
    expect(Object.keys(item!.items)).toEqual(["text/plain", "text/html"]);
    expect(await readBlob(await item!.items["text/html"]!)).toContain(
      "<strong>700 000 kr</strong>"
    );
    expect(clipboard.writeText).not.toHaveBeenCalled();
  });

  it("copies a formula as MathML", async () => {
    vi.stubGlobal("ClipboardItem", TestClipboardItem);
    clipboard.write.mockImplementation(writeItems);
    renderAnswer(mathAnswer);

    copyAsRichText();

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Kopierat"));
    const [item] = clipboard.write.mock.calls[0]![0] as TestClipboardItem[];
    expect(await readBlob(await item!.items["text/html"]!)).toContain("<math");
    expect(await readBlob(await item!.items["text/plain"]!)).toBe("Arean är \\pi r^2.");
  });

  it("says so when a formula cannot be copied as rich text, rather than copying it as code", async () => {
    vi.stubGlobal("ClipboardItem", TestClipboardItem);
    clipboard.write.mockImplementation(writeItems);
    vi.spyOn(katexStore, "load").mockResolvedValue();
    vi.spyOn(katexStore, "mathml").mockReturnValue(null);
    renderAnswer(mathAnswer);

    copyAsRichText();

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Det gick inte att kopiera. Försök igen eller markera texten och kopiera den."
      )
    );
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("falls back to plain text where the browser cannot copy HTML", async () => {
    clipboard.writeText.mockResolvedValue();
    renderAnswer();

    copyAsRichText();

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Kopierat"));
    expect(clipboard.writeText).toHaveBeenCalledWith("Gränsen är 700 000 kr.");
  });
});
