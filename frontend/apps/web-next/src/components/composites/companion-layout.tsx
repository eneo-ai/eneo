import { ResizeHandle, useResizable } from "@astryxdesign/core/Resizable";
import { useEffect, useEffectEvent, useRef, useState, type ReactNode, type RefObject } from "react";
import { useElementWidth } from "@/lib/hooks/use-element-width";
import { usePhoneScreen } from "@/lib/hooks/use-media-match";
import { cn } from "@/lib/utils";
import { CONVERSATION_MIN_WIDTH, panelFitsBeside } from "@/features/chat/side-panel/side-panel";

/** Where the aside is: beside the content, over it, or over it on a phone (the whole screen). */
export type CompanionPresentation = "beside" | "cover" | "phone";

/** The narrowest the aside gets beside the content. */
const ASIDE_MIN_WIDTH = 360;
/** Astryx's ResizeHandle with a divider takes 1 px of the row. */
const HANDLE_WIDTH = 1;

/** The nearest ancestor that scrolls up and down: the page's scroller. */
function scrollerOf(element: HTMLElement | null): HTMLElement | null {
  for (let node = element?.parentElement ?? null; node; node = node.parentElement) {
    const overflow = getComputedStyle(node).overflowY;
    if (overflow === "auto" || overflow === "scroll") return node;
  }
  return null;
}

/**
 * The height of the view the page scrolls in (its scroller's content box),
 * kept current; null until measured. The aside is that tall, so it stays in
 * view while the page scrolls beside or under it.
 */
function useViewHeight(ref: RefObject<HTMLElement | null>): number | null {
  const [height, setHeight] = useState<number | null>(null);
  useEffect(() => {
    const scroller = scrollerOf(ref.current);
    if (!scroller || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      const next = Math.round(entry?.contentRect.height ?? 0);
      if (next > 0) setHeight(next);
    });
    observer.observe(scroller);
    return () => observer.disconnect();
  }, [ref]);
  return height;
}

/**
 * A page's content with an aside the person opens and closes (a helper
 * chat beside a settings editor). The page stays the scroller: the aside
 * is sticky in the content's row, as tall as the view, so the content keeps
 * its own sticky header and lists while it scrolls.
 *
 * Beside the content while the row leaves the content 480 px (decision 14,
 * measured on the row, the chat's rule), with a handle to resize it whose
 * width is remembered (`widthStorageKey`); over the content otherwise, and
 * always on a phone, where it fills the screen and `aside` is told so (it
 * then offers a way back). While it covers the content, the content is
 * inert. The aside is mounted when it first opens and kept while it is
 * closed, so what it holds (a conversation) survives. Focus moves into it
 * when it opens, and into it when it comes to cover the content the focus
 * was in; when it closes, focus goes back to the control that opened it
 * (`returnFocus`).
 */
export function CompanionLayout({
  open,
  label,
  resizeLabel,
  widthStorageKey,
  returnFocus,
  aside,
  children
}: {
  open: boolean;
  /** The aside's name as a region. */
  label: string;
  /** The resize handle's name. */
  resizeLabel: string;
  /** Where the width the person gave the aside is kept. */
  widthStorageKey: string;
  /** The control focus goes back to when the aside closes. */
  returnFocus: () => HTMLElement | null;
  aside: (presentation: CompanionPresentation) => ReactNode;
  children: ReactNode;
}) {
  const row = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const asideRef = useRef<HTMLElement>(null);
  const phone = usePhoneScreen();
  const [mounted, setMounted] = useState(open);
  if (open && !mounted) setMounted(true);

  // Until the row is measured the aside covers the content.
  const rowWidth = useElementWidth(row);
  const viewHeight = useViewHeight(row);
  const beside = !phone && rowWidth !== null && panelFitsBeside(rowWidth);
  const presentation: CompanionPresentation = phone ? "phone" : beside ? "beside" : "cover";
  const maxWidth =
    rowWidth === null
      ? null
      : Math.max(ASIDE_MIN_WIDTH, rowWidth - HANDLE_WIDTH - CONVERSATION_MIN_WIDTH);
  const resizable = useResizable({
    containerRef: row,
    defaultSize: "40%",
    minSize: ASIDE_MIN_WIDTH,
    maxSize: maxWidth ?? "60%",
    autoSaveId: widthStorageKey
  });
  const covered = open && !beside;

  const returnFocusTo = useEffectEvent(() => returnFocus()?.focus());
  const wasOpen = useRef(open);
  useEffect(() => {
    if (open && !wasOpen.current) asideRef.current?.focus({ preventScroll: true });
    if (!open && wasOpen.current) returnFocusTo();
    wasOpen.current = open;
  }, [open]);
  // An aside that comes to cover the content (a narrower window) takes the
  // focus the content had: the content is inert under it.
  useEffect(() => {
    if (!covered) return;
    const active = document.activeElement;
    if (active === null || active === document.body || content.current?.contains(active)) {
      asideRef.current?.focus({ preventScroll: true });
    }
  }, [covered]);

  return (
    <div ref={row} data-companion-row="" className="relative flex min-w-0 flex-1 items-start">
      <div ref={content} inert={covered} className="flex min-w-0 flex-1 flex-col self-stretch">
        {children}
      </div>
      {mounted ? (
        <div
          hidden={!open}
          data-companion={presentation}
          style={viewHeight === null ? undefined : { height: viewHeight }}
          className={cn(
            "bg-ax-surface sticky top-0 z-40 flex min-w-0 shrink-0",
            // Over the content: as wide as the row, pulled back over it.
            !beside && "-ms-[100%] w-full"
          )}
        >
          {beside ? (
            // The aside sits at the end of the row: dragging the handle left widens it.
            <ResizeHandle isReversed hasDivider label={resizeLabel} resizable={resizable.props} />
          ) : null}
          <aside
            ref={asideRef}
            aria-label={label}
            tabIndex={-1}
            style={
              beside
                ? { width: maxWidth === null ? resizable.size : Math.min(resizable.size, maxWidth) }
                : undefined
            }
            className={cn(
              "flex min-h-0 min-w-0 flex-col focus-visible:outline-none",
              beside ? "shrink-0" : "flex-1"
            )}
          >
            {aside(presentation)}
          </aside>
        </div>
      ) : null}
    </div>
  );
}
