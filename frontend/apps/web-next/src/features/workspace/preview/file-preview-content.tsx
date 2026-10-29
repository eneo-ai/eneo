"use client";

import { Button } from "@astryxdesign/core/Button";
import { TextQuote } from "lucide-react";
import { useTranslations } from "use-intl";
import { useEffect, useImperativeHandle, useLayoutEffect, useRef, useState, type Ref } from "react";
import { useNonce } from "@/components/providers/nonce";
import { DocxPreview, type DocxPreviewHandle } from "./docx-preview";
import { DocumentEditor, type DocumentEditorHandle } from "./document-editor";
import type { PreviewContent } from "./load-preview";
import { PdfPreview } from "./pdf-preview";
import type { PreviewPassage } from "./preview-kind";
import {
  findPassage,
  highlightRule,
  locatePassage,
  locatorSheet,
  markPassages,
  watchSelection,
  type SelectedPassage
} from "./selection";
import { TablePreview } from "./table-preview";
import { TextPreview, TruncatedNotice } from "./text-preview";

type FilePreviewContentProps = {
  content: PreviewContent;
  title: string;
  /** A passage to mark in the content and scroll to, such as a quote sent earlier. */
  highlight: PreviewPassage | null;
  /** Called with the selected text, and where it stands, when the user quotes it. */
  onQuote: (text: string, locator: string | null) => void;
  onReady?: () => void;
  onError?: () => void;
  /** Whether a Markdown document may be edited in place. */
  editable?: boolean;
  /** The reader's unsaved text of a Markdown document, shown in place of the file's. */
  edits?: string | null;
  /** The version before this one, as Markdown; what changed against it is marked. */
  previousMarkdown?: string | null;
  /** The document's text as the reader has it; null once it is the file's again. */
  onChange?: (text: string | null) => void;
  /** The reader asked to save the document (Mod+S). */
  onSave?: () => void;
  ref?: Ref<FilePreviewContentHandle>;
};

/** The reader's edits of a Markdown document on show. */
export type FilePreviewContentHandle = {
  /** The document as the reader has it now; null unless a Markdown document is shown. */
  getMarkdown: () => string | null;
  /** Drops the reader's edits to the document on show. */
  resetEditor: () => void;
};

/** A selection and where it is, measured from the preview's top left corner. */
type Placed = { text: string; range: Range; centre: number; top: number; bottom: number };
type Size = { width: number; height: number };

// The quote action hangs on the selection: above it, or below when there is
// no room above, and never outside the preview.
const GAP = 8;

function popupPosition(selection: Placed, body: Size, popup: Size) {
  const above = selection.top - GAP - popup.height;
  const top =
    above >= GAP
      ? above
      : Math.max(GAP, Math.min(selection.bottom + GAP, body.height - popup.height - GAP));
  const left = Math.max(
    GAP,
    Math.min(selection.centre - popup.width / 2, body.width - popup.width - GAP)
  );
  return { top, left };
}

/**
 * The renderer for a loaded file, and the "Citera i chatten" action on text
 * selected in it. A Word document lives in a frame with a selection of its
 * own; every other renderer draws into the page, whose selection counts while
 * it lies wholly inside the preview. A PDF's text belongs to the browser's
 * viewer and can be reached by neither.
 */
export function FilePreviewContent({
  content,
  title,
  highlight,
  onQuote,
  onReady,
  onError,
  editable = false,
  edits = null,
  previousMarkdown = null,
  onChange,
  onSave,
  ref
}: FilePreviewContentProps) {
  const t = useTranslations();
  const nonce = useNonce();
  const bodyRef = useRef<HTMLDivElement>(null);
  const popupRef = useRef<HTMLDivElement>(null);
  const docx = useRef<DocxPreviewHandle>(null);
  const editor = useRef<DocumentEditorHandle>(null);
  const [frameSelection, setFrameSelection] = useState<Placed | null>(null);
  const [pageSelection, setPageSelection] = useState<Placed | null>(null);
  const [bodySize, setBodySize] = useState<Size>({ width: 0, height: 0 });
  const [popupSize, setPopupSize] = useState<Size>({ width: 0, height: 0 });
  const selection = frameSelection ?? pageSelection;
  // A Word document, a PDF and the document editor report readiness and
  // handle their own selection; the other renderers draw into the page.
  const drawnInPage =
    content.kind !== "docx" && content.kind !== "pdf" && content.kind !== "markdown";

  useImperativeHandle(
    ref,
    () => ({
      getMarkdown: () => editor.current?.getMarkdown() ?? null,
      resetEditor: () => editor.current?.reset()
    }),
    []
  );

  const callbacks = useRef({ onReady });
  useLayoutEffect(() => {
    callbacks.current = { onReady };
  });

  // Content drawn into the page is ready once it is in the page; a Word
  // document and a PDF report it themselves.
  useEffect(() => {
    if (drawnInPage) callbacks.current.onReady?.();
  }, [content, drawnInPage]);

  function place(passage: SelectedPassage | null): Placed | null {
    const body = bodyRef.current;
    // The editor floats its own quote action over its selection.
    if (!passage || !body || content.kind === "markdown") return null;
    const box = body.getBoundingClientRect();
    const top = passage.rect.top - box.top;
    const bottom = passage.rect.bottom - box.top;
    // Scrolled out of sight: nothing to attach to.
    if (bottom < 0 || top > box.height) return null;
    return {
      text: passage.text,
      range: passage.range,
      centre: (passage.rect.left + passage.rect.right) / 2 - box.left,
      top,
      bottom
    };
  }
  const placeRef = useRef(place);
  useLayoutEffect(() => {
    placeRef.current = place;
  });

  useEffect(() => {
    const body = bodyRef.current;
    if (!body) return;
    const watch = watchSelection(document, {
      within: () => body,
      report: (passage) => setPageSelection(placeRef.current(passage))
    });
    // Resizing the panel moves the selection without scrolling anything.
    const observer = new ResizeObserver(() => {
      setBodySize({ width: body.clientWidth, height: body.clientHeight });
      watch.refresh();
    });
    observer.observe(body);
    return () => {
      observer.disconnect();
      watch.stop();
    };
  }, []);

  const position = selection ? popupPosition(selection, bodySize, popupSize) : null;
  const showsPopup = position !== null;
  useLayoutEffect(() => {
    const popup = popupRef.current;
    if (!popup) return;
    // Pressing the button must not take the selection it is about to quote.
    const keepSelection = (event: MouseEvent) => event.preventDefault();
    popup.addEventListener("mousedown", keepSelection);
    const observer = new ResizeObserver(() =>
      setPopupSize({ width: popup.offsetWidth, height: popup.offsetHeight })
    );
    observer.observe(popup);
    return () => {
      observer.disconnect();
      popup.removeEventListener("mousedown", keepSelection);
    };
  }, [showsPopup]);

  // Marks the highlighted passage in content drawn into the page, after the
  // table has switched to the sheet the passage is on; a Word document marks
  // its own frame.
  useEffect(() => {
    const body = bodyRef.current;
    if (!body || !drawnInPage) return;
    markPassages(document, highlight ? findPassage(body, highlight.text, highlight.locator) : []);
    return () => markPassages(document, []);
  }, [content, highlight, drawnInPage]);

  function quote() {
    const body = bodyRef.current;
    if (!selection || !body) return;
    const { range, text } = selection;
    // A Word document's selection lies in its frame's document, not the page.
    const owner = range.startContainer.ownerDocument;
    const root = owner === document ? body : owner?.body;
    onQuote(text, root ? locatePassage(root, range, text) : null);
    docx.current?.clearSelection();
    if (pageSelection) document.getSelection()?.removeAllRanges();
  }

  return (
    <div ref={bodyRef} className="relative flex min-h-0 flex-1 flex-col">
      {/* The mark painted by markPassages on content drawn into the page. The
          CSS Custom Highlight pseudo-element is unknown to the bundler's CSS
          parser, so the rule is served here with the request nonce rather than
          from globals.css; a Word document's frame carries its own copy. */}
      <style nonce={nonce}>{highlightRule("var(--color-warning-muted)")}</style>
      {content.kind === "docx" ? (
        <DocxPreview
          ref={docx}
          bytes={content.bytes}
          title={title}
          highlight={highlight}
          onSelection={(passage) => setFrameSelection(place(passage))}
          onReady={onReady}
          onError={onError}
        />
      ) : content.kind === "pdf" ? (
        <PdfPreview blob={content.blob} title={title} onReady={onReady} onError={onError} />
      ) : content.kind === "table" ? (
        <TablePreview
          sheets={content.sheets}
          title={title}
          sheet={locatorSheet(highlight?.locator ?? null)}
          highlight={highlight}
          onQuote={onQuote}
        />
      ) : content.kind === "markdown" ? (
        <>
          <div className="min-h-0 flex-1 overflow-auto">
            <DocumentEditor
              ref={editor}
              markdown={content.text}
              edits={edits}
              editable={editable}
              highlight={highlight}
              previousMarkdown={previousMarkdown}
              onQuote={onQuote}
              onChange={onChange}
              onSave={onSave}
              onReady={onReady}
            />
          </div>
          {content.truncated && <TruncatedNotice />}
        </>
      ) : (
        <TextPreview text={content.text} truncated={content.truncated} />
      )}

      {position && (
        <div
          ref={popupRef}
          className="absolute z-30"
          style={{ top: position.top, left: position.left }}
        >
          <Button
            label={t("file_preview_quote_selection")}
            variant="primary"
            size="sm"
            elevation="med"
            icon={<TextQuote className="size-3.5" aria-hidden="true" />}
            onClick={quote}
          />
        </div>
      )}
    </div>
  );
}
