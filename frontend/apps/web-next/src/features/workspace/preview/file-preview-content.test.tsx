// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { FilePreviewContent } from "./file-preview-content";
import type { PreviewContent } from "./load-preview";

vi.mock("next/navigation", () => import("@/test/navigation"));

const restores: (() => void)[] = [];
/** Defines what jsdom lacks (or overrides it) until the test ends. */
function stub<T extends object>(target: T, key: PropertyKey, value: unknown) {
  const own = Object.getOwnPropertyDescriptor(target, key);
  Object.defineProperty(target, key, { configurable: true, writable: true, value });
  restores.push(() =>
    own ? Object.defineProperty(target, key, own) : Reflect.deleteProperty(target, key)
  );
}

afterEach(() => {
  cleanup();
  window.getSelection()?.removeAllRanges();
  vi.restoreAllMocks();
  restores
    .splice(0)
    .reverse()
    .forEach((restore) => restore());
});

function renderContent(content: PreviewContent) {
  const onQuote = vi.fn();
  const onReady = vi.fn();
  const view = renderInApp(
    <FilePreviewContent
      content={content}
      title="anteckningar.txt"
      highlight={null}
      onQuote={onQuote}
      onReady={onReady}
    />
  );
  return { onQuote, onReady, ...view };
}

/** Gives jsdom, which has no layout, a preview box and a box for every selected range. */
function giveLayout() {
  const box = { left: 0, top: 0, right: 400, bottom: 400, width: 400, height: 400, x: 0, y: 0 };
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
    ...box,
    toJSON: () => box
  });
  const selected = {
    left: 40,
    top: 100,
    right: 80,
    bottom: 116,
    width: 40,
    height: 16,
    x: 40,
    y: 100
  };
  stub(Range.prototype, "getBoundingClientRect", () => ({ ...selected, toJSON: () => selected }));
}

/** Selects `length` characters of `node`'s text from `start`, as a settled selection. */
function select(node: Node, start: number, length: number) {
  const range = document.createRange();
  range.setStart(node, start);
  range.setEnd(node, start + length);
  const selection = window.getSelection()!;
  selection.removeAllRanges();
  selection.addRange(range);
  act(() => {
    document.dispatchEvent(new Event("selectionchange"));
  });
}

it("shows plain text as written, says when only its beginning was read, and is ready", () => {
  const { onReady, container } = renderContent({
    kind: "text",
    text: "Rad ett\n  Rad två",
    truncated: true
  });
  expect(container.querySelector("pre")?.textContent).toBe("Rad ett\n  Rad två");
  expect(screen.getByText("Visar början av filen. Ladda ner den för att se allt.")).toBeTruthy();
  expect(onReady).toHaveBeenCalledOnce();
});

it("renders Markdown as an answer would", () => {
  renderContent({ kind: "markdown", text: "# Protokoll\n\nPunkt **ett**", truncated: false });
  expect(screen.getByRole("heading", { name: "Protokoll" })).toBeTruthy();
  expect(screen.queryByText("Visar början av filen. Ladda ner den för att se allt.")).toBeNull();
});

it("offers to quote selected text, with which occurrence it is", async () => {
  giveLayout();
  const { onQuote, container } = renderContent({
    kind: "text",
    text: "alfa beta alfa",
    truncated: false
  });
  expect(screen.queryByRole("button", { name: "Citera i chatten" })).toBeNull();

  select(container.querySelector("pre")!.firstChild!, 10, 4);
  const quote = screen.getByRole("button", { name: "Citera i chatten" });
  await expectNoAxeViolations(document.body);

  fireEvent.click(quote);
  expect(onQuote).toHaveBeenCalledWith("alfa", "occurrence 2 of 2");
  expect(window.getSelection()?.isCollapsed).toBe(true);
});

it("does not offer a quote for a selection outside the preview", () => {
  giveLayout();
  renderContent({ kind: "text", text: "Innehåll", truncated: false });
  const outside = document.createElement("p");
  outside.textContent = "Utanför";
  document.body.append(outside);
  select(outside.firstChild!, 0, 7);
  expect(screen.queryByRole("button", { name: "Citera i chatten" })).toBeNull();
  outside.remove();
});

it("shows a PDF in the browser's viewer and releases its URL when closed", () => {
  const revokeObjectURL = vi.fn();
  stub(URL, "createObjectURL", () => "blob:preview");
  stub(URL, "revokeObjectURL", revokeObjectURL);
  const { container, unmount } = renderContent({
    kind: "pdf",
    blob: new Blob(["%PDF"], { type: "application/pdf" })
  });
  expect(container.querySelector("iframe")?.getAttribute("src")).toBe(
    "blob:preview#navpanes=0&view=FitH"
  );
  unmount();
  expect(revokeObjectURL).toHaveBeenCalledWith("blob:preview");
});

it("asks for a download where the browser has no PDF viewer", () => {
  stub(navigator, "pdfViewerEnabled", false);
  const { onReady } = renderContent({ kind: "pdf", blob: new Blob(["%PDF"]) });
  expect(
    screen.getByText(
      "Webbläsaren kan inte visa PDF-filer här. Ladda ner filen för att se innehållet."
    )
  ).toBeTruthy();
  expect(onReady).toHaveBeenCalled();
});
