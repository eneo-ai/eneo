import { useLayoutEffect, useRef, type ReactNode } from "react";

/**
 * A screen's primary action, docked at the bottom on a phone, held either way
 * (one primary per screen, in the thumb zone: the artifact's DockedActions),
 * and in its place in the page otherwise. One element that CSS moves, so
 * nothing remounts when a turn changes the layout: a dialog the action opened
 * stays open with what was typed in it.
 *
 * On a phone it is fixed over the page's bottom edge and padded clear of the
 * home indicator. Its buttons share a row (below 640 px) while their labels fit and
 * wrap to rows of their own at larger text, rather than cutting the labels
 * short; from 640 px each keeps its own width, at the end of the bar. It
 * publishes its height as `--docked-actions-height`: main#main-content
 * reserves that much (app-shell), so the last row scrolls clear of it and
 * focus stops above it (WCAG 2.4.11), and the toasts rest above it
 * (globals.css section 14b). Fixed, it leaves the page's flow: a flex
 * container it sits in adds no gap for it. On a touch phone turned sideways
 * it gives way while a text field in the page has focus: with the software
 * keyboard up it would cover the field being typed in. A switch or a checkbox
 * opens no keyboard, so the bar stays. Sideways is told by width: an upright
 * phone's bar rises above its keyboard, and that keyboard can leave a small
 * phone's window wider than tall, so `landscape:` would match it too.
 */
export function DockedActions({ label, children }: { label: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const bar = ref.current;
    if (!bar) return;
    const root = document.documentElement;
    const publish = () => {
      if (getComputedStyle(bar).position === "fixed") {
        root.style.setProperty("--docked-actions-height", `${bar.offsetHeight}px`);
      } else {
        root.style.removeProperty("--docked-actions-height");
      }
    };
    const observer = new ResizeObserver(publish);
    observer.observe(bar);
    publish();
    return () => {
      observer.disconnect();
      root.style.removeProperty("--docked-actions-height");
    };
  }, []);

  return (
    <div
      ref={ref}
      role="group"
      aria-label={label}
      data-docked-actions=""
      className="phone:border-ax-border phone:bg-ax-surface phone:fixed phone:inset-x-0 phone:bottom-0 phone:z-10 phone:border-t phone:px-4 phone:pt-3 phone:pb-[calc(0.75rem+env(safe-area-inset-bottom,0px))] phone:[&>*]:min-w-0 phone:short:pointer-coarse:min-[30rem]:group-has-[main_:is(input:not([type=checkbox],[type=radio],[type=file],[type=range],[type=button],[type=submit]),textarea,[contenteditable=true]):focus]/shell:invisible flex flex-wrap justify-end gap-2 max-sm:[&>*]:flex-[1_1_auto]"
    >
      {children}
    </div>
  );
}
