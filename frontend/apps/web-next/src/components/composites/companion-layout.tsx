import { useScrollableArea } from "@astryxdesign/core/hooks";
import { ResizeHandle, useResizable } from "@astryxdesign/core/Resizable";
import {
  Component,
  useEffect,
  useEffectEvent,
  useRef,
  useState,
  type ReactNode,
  type RefObject
} from "react";
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
 * view while the page scrolls beside or under it, and so is the row while the
 * content scrolls on its own beside the aside.
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
 * Where the person is reading: an element at the top of the view, and where
 * it is against that top. One that starts below it keeps how far below
 * (`offset`). One the top crosses keeps the share of it above the top
 * (`share`): where it reflows (a description that wraps onto one more line),
 * the same part of it stays at the top, and what follows it moves only by
 * what it grew below the top.
 */
type ReadingPlace = { element: Element; offset: number } | { element: Element; share: number };

/** A child of the content as `readingPlace` reads it. */
type Laid = { child: Element; box: DOMRect; position: string };

/**
 * The top of what `scroller` shows of `content`, below what sticks there (a
 * sticky header), and the person's place under it: the element that reaches
 * below that line and starts highest (in a row, the item that starts with
 * the row, not one centred in it), stepping into one that starts on or above
 * it (where what sticks may be) until one starts below it or has nothing to
 * step into, so a long section gives a place inside it. Sticky and
 * positioned elements are no place: they stay where they are.
 */
function readingPlace(
  scroller: HTMLElement,
  content: HTMLElement
): { line: number; place: ReadingPlace | null } {
  const top = scroller.getBoundingClientRect().top;
  let line = top;
  let place: ReadingPlace | null = null;
  let parent: Element | null = content;
  while (parent) {
    const children: Laid[] = [...parent.children].flatMap((child): Laid[] => {
      const box = child.getBoundingClientRect();
      // Above the view, or no box: neither a place nor what sticks at its top.
      if (box.height === 0 || box.bottom <= top) return [];
      return [{ child, box, position: getComputedStyle(child).position }];
    });
    for (const { box, position } of children) {
      // Resting against the top of the view, it hides what scrolls under it.
      if (position === "sticky" && box.top <= top + 1 && box.bottom > line) line = box.bottom;
    }
    let next: Laid | null = null;
    for (const candidate of children) {
      if (["sticky", "fixed", "absolute"].includes(candidate.position)) continue;
      if (candidate.box.bottom <= line) continue;
      if (!next || candidate.box.top < next.box.top) next = candidate;
    }
    if (!next) break;
    const { child, box } = next;
    place =
      box.top <= line
        ? { element: child, share: (line - box.top) / box.height }
        : { element: child, offset: box.top - line };
    parent = box.top <= line ? child : null;
  }
  return { line, place };
}

/**
 * Keeps the person's place in the content when the scroller that shows it
 * changes (the content starts or stops scrolling on its own as the aside
 * opens or closes beside it, or the window changes the aside's room): what
 * is at the top of the view stays there, however the content's new width
 * reflows it (`ReadingPlace`). The place is read before the change is drawn
 * (`getSnapshotBeforeUpdate`, which no hook offers) and restored after it,
 * before the change is painted.
 */
class ReadingPlaceKeeper extends Component<{
  ownScroll: boolean;
  row: RefObject<HTMLElement | null>;
  /** The content's column; its one child is its own scroller while it has one. */
  content: RefObject<HTMLElement | null>;
}> {
  private scroller(ownScroll: boolean): HTMLElement | null {
    const own = this.props.content.current?.firstElementChild;
    return ownScroll
      ? own instanceof HTMLElement
        ? own
        : null
      : scrollerOf(this.props.row.current);
  }

  override getSnapshotBeforeUpdate(previous: ReadingPlaceKeeper["props"]): ReadingPlace | null {
    const content = this.props.content.current;
    const scroller = this.scroller(previous.ownScroll);
    if (previous.ownScroll === this.props.ownScroll || !content || !scroller) return null;
    return readingPlace(scroller, content).place;
  }

  override componentDidUpdate(
    _previous: ReadingPlaceKeeper["props"],
    _state: unknown,
    place: ReadingPlace | null
  ) {
    const content = this.props.content.current;
    const scroller = this.scroller(this.props.ownScroll);
    if (!place || !content || !scroller || !place.element.isConnected) return;
    const { line } = readingPlace(scroller, content);
    const box = place.element.getBoundingClientRect();
    const top = "share" in place ? line - place.share * box.height : line + place.offset;
    scroller.scrollTop += box.top - top;
  }

  override render() {
    return null;
  }
}

/**
 * A page's content with an aside the person opens and closes (a helper
 * chat beside a settings editor). The aside is sticky in the content's row,
 * as tall as the view the page scrolls in. While it is open beside the
 * content, the content scrolls on its own, its scrollbar at its own edge
 * beside the aside, and the page holds still: a named region
 * (`contentLabel`) whose keyboard entry goes to its first link or button,
 * as a table's scroll box does. Otherwise the page is the scroller, as
 * without the aside. Either way the content keeps its own sticky header and
 * lists, and the person keeps their place when the scroller changes.
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
 * (`returnFocus`). With `onClose`, Escape in an aside that covers the
 * content closes it, once nothing in the aside took that Escape for itself
 * (a menu, a popover, a dialog, a composer's suggestions); beside the
 * content Escape leaves it open.
 */
export function CompanionLayout({
  open,
  label,
  contentLabel,
  resizeLabel,
  widthStorageKey,
  returnFocus,
  onClose,
  aside,
  children
}: {
  open: boolean;
  /** The aside's name as a region. */
  label: string;
  /** The content's name as a region, while it scrolls on its own beside the aside. */
  contentLabel: string;
  /** The resize handle's name. */
  resizeLabel: string;
  /** Where the width the person gave the aside is kept. */
  widthStorageKey: string;
  /** The control focus goes back to when the aside closes. */
  returnFocus: () => HTMLElement | null;
  /** Closes the aside: Escape asks for it while the aside covers the content. */
  onClose?: () => void;
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
  // Beside the open aside, the content is its own scroller. Its sticky header
  // and lists stick to it whatever its length, and the page's scroll does
  // not carry on into it from its ends.
  const ownScroll = open && beside;
  const contentScroll = useScrollableArea({
    axis: "block",
    keyboardAccess: { owner: "contentOrViewport", label: contentLabel, role: "region" },
    overscroll: "contain",
    stickyContainment: "always"
  });
  // A tab stop only while it scrolls and its keyboard entry has no link or
  // button to go to; its ring is drawn inside, where its edges do not clip it.
  // Positioned, so what is absolutely positioned in the content (text for
  // screen readers, a field's floating label) scrolls with it and is clipped
  // by it; placed against the row instead, it would give the page its own
  // height to scroll.
  const viewportClassName =
    "focus-visible:outline-ring relative flex min-h-0 min-w-0 flex-1 flex-col focus-visible:outline-2 focus-visible:-outline-offset-2";

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

  // Escape closes an aside over the content. It is heard on the window, after
  // the document, where Astryx's layers (menus, popovers, dialogs, tooltips)
  // and a composer's suggestions claim an Escape they act on by preventing
  // its default; a press inside a dialog is that dialog's in any case.
  const close = useEffectEvent(() => onClose?.());
  const closable = covered && onClose !== undefined;
  useEffect(() => {
    if (!closable) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented || event.isComposing) return;
      const target = event.target;
      if (!(target instanceof Element) || !asideRef.current?.contains(target)) return;
      if (target.closest("dialog, [role='dialog'], [role='alertdialog']")) return;
      event.preventDefault();
      close();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [closable]);

  return (
    <div
      ref={row}
      data-companion-row=""
      // As tall as the view while the content scrolls on its own: the page has
      // nothing to scroll. Not flexible then: in a frame that is as tall as
      // its content, a flexible row takes the content's height instead.
      style={ownScroll && viewHeight !== null ? { height: viewHeight, flex: "none" } : undefined}
      className="relative flex min-w-0 flex-1 items-start"
    >
      <div ref={content} inert={covered} className="flex min-w-0 flex-1 flex-col self-stretch">
        {/* The same elements in either state, so the content is never mounted again. */}
        <div
          {...(ownScroll
            ? contentScroll.getViewportProps<HTMLDivElement>({ className: viewportClassName })
            : { className: viewportClassName })}
        >
          <div {...contentScroll.getContentProps({ className: "flex min-w-0 shrink-0 flex-col" })}>
            {children}
          </div>
        </div>
      </div>
      <ReadingPlaceKeeper ownScroll={ownScroll} row={row} content={content} />
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
