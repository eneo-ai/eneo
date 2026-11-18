// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";

beforeEach(() => vi.resetModules());
afterEach(() => {
  vi.doUnmock("@/components/ai-elements/answer-clipboard");
  vi.unstubAllGlobals();
});

it("loads the renderer only for rich text and starts the clipboard write before it arrives", async () => {
  let arrive!: () => void;
  const pending = new Promise<void>((resolve) => (arrive = resolve));
  const load = vi.fn(async () => {
    await pending;
    return {
      renderAnswerForClipboard: () => ({ plainText: "Answer", html: async () => "<p>Answer</p>" })
    };
  });
  vi.doMock("@/components/ai-elements/answer-clipboard", load);
  const { assistantClipboardContent, copyRichText } = await import("./copy-assistant-answer");
  expect(assistantClipboardContent("**Answer**", "markdown")).toEqual({
    text: "**Answer**",
    html: null
  });
  expect(load).not.toHaveBeenCalled();

  class Item {
    constructor(readonly data: Record<string, Promise<Blob>>) {}
  }
  vi.stubGlobal("ClipboardItem", Item);
  const write = vi.fn(async (items: Item[]) => {
    await Promise.all(Object.values(items[0]!.data));
  });
  vi.stubGlobal("navigator", { clipboard: { write } });
  const { text, html } = assistantClipboardContent("**Answer**", "richtext");
  const copied = copyRichText({ text, html: html! });
  expect(write).toHaveBeenCalledOnce();
  await vi.waitFor(() => expect(load).toHaveBeenCalledOnce());
  arrive();
  await expect(copied).resolves.toBe(true);
});

it.each([false, true])(
  "reports a renderer failure when the clipboard also refuses: %s",
  async (refused) => {
    vi.doMock("@/components/ai-elements/answer-clipboard", () => {
      throw new Error("Failed to fetch dynamically imported module");
    });
    class Item {
      constructor(readonly data: Record<string, Promise<Blob>>) {
        if (refused) throw new DOMException("denied", "NotAllowedError");
      }
    }
    vi.stubGlobal("ClipboardItem", Item);
    vi.stubGlobal("navigator", {
      clipboard: { write: async (items: Item[]) => Promise.all(Object.values(items[0]!.data)) }
    });
    const { assistantClipboardContent, copyRichText } = await import("./copy-assistant-answer");
    const { text, html } = assistantClipboardContent("**Answer**", "richtext");
    await expect(copyRichText({ text, html: html! })).resolves.toBe(false);
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
);
