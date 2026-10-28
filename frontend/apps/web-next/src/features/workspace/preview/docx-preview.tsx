"use client";

import { useTranslations } from "next-intl";
import {
  useCallback,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useRef,
  useState,
  type Ref
} from "react";
import { useNonce } from "@/components/providers/nonce";
import { sanitizeLinkHref } from "@/lib/safe-url";
import { cn } from "@/lib/utils";
import type { PreviewPassage } from "./preview-kind";
import {
  findPassage,
  highlightRule,
  markPassages,
  watchSelection,
  type SelectedPassage
} from "./selection";

export type DocxPreviewHandle = {
  /** Drops the selection in the document, as after it has been quoted. */
  clearSelection: () => void;
};

type DocxPreviewProps = {
  bytes: ArrayBuffer;
  title: string;
  /** A passage to mark in the document and scroll to. */
  highlight?: PreviewPassage | null;
  /** Reports the settled selection in the document, placed in the page's viewport. */
  onSelection?: (passage: SelectedPassage | null) => void;
  onReady?: () => void;
  onError?: () => void;
  ref?: Ref<DocxPreviewHandle>;
};

// The document is laid out in a frame of its own: Word styles and the app's
// styles cannot reach each other, and the sandbox (no allow-scripts) keeps
// anything a document carries from running. Same-origin so the page can build
// the frame's content (the frame inherits the page's CSP, so every style in it
// carries the request nonce); popups so a link opens in a new tab.
const SANDBOX = "allow-same-origin allow-popups allow-popups-to-escape-sandbox";
const SHELL = '<!doctype html><html><head><meta charset="utf-8"></head><body></body></html>';
const PAGE_GUTTER = 16;

/**
 * The frame's own rules, after the renderer's so they win. The frame has no
 * theme of its own: the page's shadow and highlight tokens are copied in, and
 * resolve to their light values there, since the pages are white paper in
 * either colour mode.
 */
function frameStyle(tokens: CSSStyleDeclaration): string {
  const shadow = tokens.getPropertyValue("--shadow-low").trim() || "none";
  const mark = tokens.getPropertyValue("--color-warning-muted").trim() || "Mark";
  return `
    body { margin: 0; }
    .docx-wrapper { background: transparent; padding: ${PAGE_GUTTER}px; }
    .docx-wrapper > section.docx { margin-bottom: ${PAGE_GUTTER}px; box-shadow: ${shadow}; }
    ${highlightRule(mark)}
  `;
}

/** Every `<style>` in `node`, itself included. */
function stylesIn(node: Node): Element[] {
  if (!(node instanceof Element)) return [];
  return [...(node.nodeName === "STYLE" ? [node] : []), ...node.querySelectorAll("style")];
}

/**
 * Puts the renderer's output into the frame's document. A style counts only
 * with the nonce it carried when it was inserted, so every one gets it first.
 */
function fillFrame(
  frame: HTMLIFrameElement,
  frameDocument: Document,
  nodes: Node[],
  nonce: string | undefined
) {
  const style = frameDocument.createElement("style");
  style.textContent = frameStyle(getComputedStyle(frame));
  for (const element of [...nodes.flatMap(stylesIn), style]) {
    if (nonce) element.setAttribute("nonce", nonce);
  }
  for (const node of nodes) {
    (node.nodeName === "STYLE" ? frameDocument.head : frameDocument.body).appendChild(node);
  }
  // Last, so it overrides the renderer's own wrapper styles.
  frameDocument.head.append(style);
  // The backdrop behind the pages follows the app's theme. It is copied in:
  // the frame keeps the light colour scheme its paper needs, and a frame
  // whose scheme differs from the page's is never transparent.
  if (frame.parentElement) {
    frameDocument.documentElement.style.background = getComputedStyle(
      frame.parentElement
    ).backgroundColor;
  }
  for (const link of frameDocument.querySelectorAll("a")) {
    const href = sanitizeLinkHref(link.getAttribute("href"));
    if (!href) link.removeAttribute("href");
    else if (!href.startsWith("#")) {
      link.target = "_blank";
      link.rel = "noopener noreferrer";
    }
  }
}

// A new document gets a fresh frame: the frame renders once, on its load.
const documentKeys = new WeakMap<ArrayBuffer, number>();
let nextDocumentKey = 0;
function documentKey(bytes: ArrayBuffer): number {
  let key = documentKeys.get(bytes);
  if (key === undefined) documentKeys.set(bytes, (key = nextDocumentKey++));
  return key;
}

/** A Word document rendered by docx-preview into a sandboxed frame, scaled to its width. */
export function DocxPreview(props: DocxPreviewProps) {
  return <DocxFrame key={documentKey(props.bytes)} {...props} />;
}

function DocxFrame({
  bytes,
  title,
  highlight = null,
  onSelection,
  onReady,
  onError,
  ref
}: DocxPreviewProps) {
  const t = useTranslations();
  const nonce = useNonce();
  const frameRef = useRef<HTMLIFrameElement>(null);
  const watchRef = useRef<ReturnType<typeof watchSelection> | null>(null);
  // Width of a page as Word laid it out, measured once before any scaling.
  const pageWidth = useRef(0);
  const [status, setStatus] = useState<"rendering" | "ready" | "failed">("rendering");

  const callbacks = useRef({ onSelection, onReady, onError });
  useLayoutEffect(() => {
    callbacks.current = { onSelection, onReady, onError };
  });

  useImperativeHandle(
    ref,
    () => ({
      clearSelection: () => frameRef.current?.contentDocument?.getSelection()?.removeAllRanges()
    }),
    []
  );

  /** Scales the pages down to the frame's width; never up. */
  const fit = useCallback(() => {
    const frame = frameRef.current;
    const wrapper = frame?.contentDocument?.querySelector<HTMLElement>(".docx-wrapper");
    if (!frame || !wrapper || pageWidth.current === 0) return;
    const scale = Math.min(1, frame.clientWidth / (pageWidth.current + 2 * PAGE_GUTTER));
    wrapper.style.zoom = String(scale);
    // Scaling moved whatever is selected.
    watchRef.current?.refresh();
  }, []);

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    const observer = new ResizeObserver(fit);
    observer.observe(frame);
    return () => {
      observer.disconnect();
      watchRef.current?.stop();
    };
  }, [fit]);

  useEffect(() => {
    const frameDocument = frameRef.current?.contentDocument;
    if (status !== "ready" || !frameDocument) return;
    markPassages(
      frameDocument,
      highlight ? findPassage(frameDocument.body, highlight.text, highlight.locator) : []
    );
  }, [status, highlight]);

  async function render() {
    const frame = frameRef.current;
    const frameDocument = frame?.contentDocument;
    if (!frame || !frameDocument || watchRef.current) return;
    try {
      const { parseAsync, renderDocument } = await import("docx-preview");
      // Images inline as data URLs: object URLs would outlive the preview.
      const options = { inWrapper: true, useBase64URL: true };
      const nodes = await renderDocument(await parseAsync(bytes, options), options);
      if (!frame.isConnected) return;

      fillFrame(frame, frameDocument, nodes, nonce);
      // The frame's document has a selection of its own, which the page reads
      // here; the frame's place in the page turns its coordinates into the page's.
      watchRef.current = watchSelection(frameDocument, {
        origin: () => {
          const box = frame.getBoundingClientRect();
          return { x: box.left, y: box.top };
        },
        report: (passage) => callbacks.current.onSelection?.(passage)
      });
      pageWidth.current =
        frameDocument.querySelector<HTMLElement>("section.docx")?.offsetWidth ?? 0;
      fit();
      setStatus("ready");
      callbacks.current.onReady?.();
    } catch {
      setStatus("failed");
      callbacks.current.onError?.();
    }
  }

  return (
    <div className="bg-ax-muted relative min-h-0 flex-1">
      {status === "failed" ? (
        <p className="text-ax-text-secondary p-6 text-sm">{t("file_preview_failed")}</p>
      ) : (
        <>
          <iframe
            ref={frameRef}
            title={title}
            sandbox={SANDBOX}
            srcDoc={SHELL}
            onLoad={() => void render()}
            className={cn(
              "absolute inset-0 h-full w-full border-0",
              status !== "ready" && "invisible"
            )}
          />
          {status === "rendering" && (
            <p className="text-ax-text-secondary absolute inset-0 p-6 text-sm">
              {t("file_preview_loading")}
            </p>
          )}
        </>
      )}
    </div>
  );
}
