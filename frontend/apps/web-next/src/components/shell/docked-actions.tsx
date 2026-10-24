import type { ReactNode } from "react";

/**
 * A screen's primary action, docked at the bottom on a phone (one primary per
 * screen, in the thumb zone: the artifact's DockedActions) and in its place
 * in the page from 768 px. One element that CSS moves, so nothing remounts
 * when a turn crosses 768 px: a dialog the action opened stays open with
 * what was typed in it.
 *
 * On a phone it is fixed over the page's bottom edge and padded clear of the
 * home indicator. main#main-content reserves its height (app-shell), so the
 * last row scrolls clear of it and focus stops above it (WCAG 2.4.11), and
 * the toasts rest above it (globals.css section 14b). Fixed, it leaves the
 * page's flow: a flex container it sits in adds no gap for it.
 */
export function DockedActions({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div
      role="group"
      aria-label={label}
      data-docked-actions=""
      className="max-md:border-ax-border max-md:bg-ax-surface flex flex-wrap justify-end gap-2 max-md:fixed max-md:inset-x-0 max-md:bottom-0 max-md:z-10 max-md:flex-nowrap max-md:border-t max-md:px-4 max-md:pt-3 max-md:pb-[calc(0.75rem+env(safe-area-inset-bottom,0px))] max-md:[&_.astryx-button]:w-full max-md:[&>*]:min-w-0 max-md:[&>*]:flex-1"
    >
      {children}
    </div>
  );
}
