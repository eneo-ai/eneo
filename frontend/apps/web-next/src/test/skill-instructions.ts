import { fireEvent } from "@testing-library/react";

/** Replace literal instructions through the editor's keyboard and clipboard boundary. */
export function replaceInstructionText(editor: HTMLElement, text: string) {
  // jsdom has no Range geometry. Scrolling and caret placement are verified in Chromium.
  if (!Range.prototype.getClientRects) {
    Object.defineProperty(Range.prototype, "getClientRects", {
      configurable: true,
      value: () => []
    });
    Object.defineProperty(Range.prototype, "getBoundingClientRect", {
      configurable: true,
      value: () => new DOMRect()
    });
  }
  editor.focus();
  fireEvent.keyDown(editor, { key: "a", ctrlKey: true });
  fireEvent.paste(editor, {
    clipboardData: { getData: (type: string) => (type === "text/plain" ? text : "") }
  });
}
