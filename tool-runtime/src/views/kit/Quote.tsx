/// <reference lib="dom" />
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Button } from "@astryxdesign/core/Button";
import { pick, useViewHost } from "./host";

const TEXTS = {
  sv: { quote: "Citera i chatten" },
  en: { quote: "Quote in chat" },
};

/** A quote points at a passage; it does not hand the view over. A longer selection is cut. */
const MAX_QUOTE_LENGTH = 4000;
const GAP = 8;

// Lucide's text-quote, like the host's own offer to quote a selection.
const quoteIcon = (
  <svg
    width="16"
    height="16"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="M17 5H3" />
    <path d="M21 12H8" />
    <path d="M21 19H8" />
    <path d="M3 12v7" />
  </svg>
);

/** The selected text, and where it ends: the line the reader stopped on. */
type Selected = { text: string; top: number; bottom: number; centre: number; backward: boolean };

function readSelection(): Selected | null {
  const field = document.activeElement;
  // Text selected in a field is being written, not pointed at.
  if (field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement) return null;
  const selection = document.getSelection();
  if (!selection || selection.isCollapsed || selection.rangeCount === 0) return null;
  const text = selection.toString().trim();
  if (!text) return null;
  const range = selection.getRangeAt(0);
  const { anchorNode, anchorOffset, focusNode, focusOffset } = selection;
  const order = anchorNode && focusNode ? anchorNode.compareDocumentPosition(focusNode) : 0;
  const backward =
    order === 0 ? anchorOffset > focusOffset : Boolean(order & Node.DOCUMENT_POSITION_PRECEDING);
  // A selection over many rows can be taller than the screen; its last line is in sight.
  const lines = range.getClientRects();
  const box = (backward ? lines[0] : lines[lines.length - 1]) ?? range.getBoundingClientRect();
  if (box.width === 0 && box.height === 0) return null;
  return { text, top: box.top, bottom: box.bottom, centre: (box.left + box.right) / 2, backward };
}

/**
 * The offer to quote what the reader has selected in the view, hung on the selection. Taking
 * it tells the host the text (`ui/update-model-context`), which shows it with the message
 * being written and sends it with the next question. A host that takes no context is not
 * offered any.
 */
export function QuoteSelection() {
  const { app, context, connected } = useViewHost();
  const text = pick(context, TEXTS);
  const offered = connected && Boolean(app.getHostCapabilities()?.updateModelContext);
  const [selected, setSelected] = useState<Selected | null>(null);
  const offer = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!offered) return;
    let dragging = false;
    const read = () => setSelected(readSelection());
    // Nothing is offered while the pointer is still dragging the selection out.
    const change = () => (dragging ? setSelected(null) : read());
    const press = () => {
      dragging = true;
    };
    const release = () => {
      dragging = false;
      // A click's own selection change lands after the pointer is released.
      setTimeout(read);
    };
    const moved = () => {
      if (!dragging) read();
    };
    document.addEventListener("selectionchange", change);
    document.addEventListener("pointerdown", press, true);
    document.addEventListener("pointerup", release, true);
    document.addEventListener("pointercancel", release, true);
    document.addEventListener("scroll", moved, true);
    window.addEventListener("resize", moved);
    return () => {
      document.removeEventListener("selectionchange", change);
      document.removeEventListener("pointerdown", press, true);
      document.removeEventListener("pointerup", release, true);
      document.removeEventListener("pointercancel", release, true);
      document.removeEventListener("scroll", moved, true);
      window.removeEventListener("resize", moved);
    };
  }, [offered]);

  // Past the end of the selection, on the side the reader stopped; never outside the view.
  useLayoutEffect(() => {
    const element = offer.current;
    if (!element || !selected) return;
    const { offsetWidth: width, offsetHeight: height } = element;
    const above = selected.top - GAP - height;
    const below = selected.bottom + GAP;
    const fits = (top: number) => top >= GAP && top + height + GAP <= window.innerHeight;
    const [first, second] = selected.backward ? [above, below] : [below, above];
    const top = fits(first)
      ? first
      : fits(second)
        ? second
        : Math.max(GAP, Math.min(first, window.innerHeight - height - GAP));
    const left = Math.max(
      GAP,
      Math.min(selected.centre - width / 2, window.innerWidth - width - GAP),
    );
    element.style.top = `${top}px`;
    element.style.left = `${left}px`;
  }, [selected, text]);

  if (!selected) return null;
  const quote = () => {
    void app
      .updateModelContext({
        content: [{ type: "text", text: selected.text.slice(0, MAX_QUOTE_LENGTH) }],
      })
      .catch(() => undefined);
    document.getSelection()?.removeAllRanges();
    setSelected(null);
  };
  return (
    <div
      ref={offer}
      className="eneo-quote"
      // Pressing the button must not take the selection it is about to quote. The host takes
      // a quote only from the view the reader is in, which a prevented press would not say.
      onMouseDown={(event) => {
        event.preventDefault();
        window.focus();
      }}
    >
      <Button variant="primary" size="sm" label={text.quote} icon={quoteIcon} onClick={quote} />
    </div>
  );
}
