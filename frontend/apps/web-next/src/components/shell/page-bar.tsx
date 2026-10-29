"use client";

import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { ChevronLeft } from "lucide-react";
import { useTranslations } from "use-intl";
import { useLayoutEffect, useRef, useState } from "react";
import { SamePageLink, type InPlaceLink } from "@/components/composites/in-place-link";
import { cn } from "@/lib/utils";
import { ConnectionBanner } from "./connection-banner";
import { OWN_MOBILE_HEADER, OWN_PHONE_HEADER } from "./shell-context";

export type PageBarProps = {
  /**
   * Where the back link goes: the screen the user came down from. With
   * `onClick` (an `inPlaceLink`) it goes back within the page, as an editor's
   * section does to the editor's index.
   */
  parent: { label: string; href: string; onClick?: InPlaceLink["onClick"] };
  /**
   * The page's title, shown in the bar once the page's own h1 has scrolled
   * under it, or from the start with `isTitleShown` (a page whose h1 is not
   * visible on a phone). Decoration: the h1 stays the page's heading.
   */
  title?: string;
  isTitleShown?: boolean;
  /** Page actions at the end of the bar. */
  actions?: React.ReactNode;
  /**
   * Below which width the bar replaces the shell's top bar: `lg` (1024 px,
   * every pushed screen) or `md` (768 px: a space, which tablets show with
   * breadcrumbs under the top bar).
   */
  until?: "lg" | "md";
};

/**
 * The header of a pushed screen below 1024px (an admin area; later a space
 * page or an editor): a back link that names where it goes (decision 20),
 * the title once the page has scrolled, and actions. It replaces the shell's
 * top bar (`OWN_MOBILE_HEADER`), so the menu is one tap back, on the parent.
 * Render it first in main#main-content, outside the page's padding: it
 * sticks to the top of the page panel.
 */
export function PageBar({
  parent,
  title,
  isTitleShown = false,
  actions,
  until = "lg"
}: PageBarProps) {
  const t = useTranslations();
  const phone = until === "md";
  const backRef = useRef<HTMLDivElement>(null);
  const back = useBackLabel(backRef, [parent.label, t("back")]);
  return (
    <>
      {/* The title is centred between equal sides. A parent name that does not
          fit beside it reads "Tillbaka" (decision 39), and where that does not
          fit either, the arrow alone; the link's accessible name keeps all of
          it. */}
      <div
        {...(phone ? OWN_PHONE_HEADER : OWN_MOBILE_HEADER)}
        // main#main-content keeps focused and scrolled-to content clear of it (app-shell.tsx).
        {...(phone ? { "data-phone-page-bar": "" } : { "data-page-bar": "" })}
        className={cn(
          "bg-ax-surface border-ax-border sticky top-0 z-10 grid h-14 shrink-0 grid-cols-[minmax(0,1fr)_minmax(0,auto)_minmax(max-content,1fr)] items-center gap-1 border-b px-1.5",
          phone ? "md:hidden" : "lg:hidden"
        )}
      >
        <div ref={backRef} className="min-w-0">
          <Button
            href={parent.href}
            {...(parent.onClick ? { onClick: parent.onClick, as: SamePageLink } : {})}
            variant="ghost"
            size="lg"
            icon={<Icon icon={ChevronLeft} />}
            // Astryx names an icon-only button by its label: the full name then.
            label={
              back === 2
                ? t("shell_back_to", { name: parent.label })
                : back === 1
                  ? t("back")
                  : parent.label
            }
            isIconOnly={back === 2}
            aria-label={t("shell_back_to", { name: parent.label })}
            className="text-ax-text-accent max-w-full min-w-0"
          />
        </div>
        <span
          aria-hidden="true"
          className={cn(
            "truncate text-center text-sm font-semibold",
            "max-w-[50vw]",
            !isTitleShown && "page-bar-title"
          )}
        >
          {title}
        </span>
        <div className="flex items-center justify-self-end">{actions}</div>
      </div>
      {/* Under the bar, not in it: the bar is hidden from 1024px, the banner is
          not. Where the bar is for phones only, the shell's banner is back
          from 768px, and this one gives way to it. */}
      <ConnectionBanner className={phone ? "md:hidden" : undefined} />
    </>
  );
}

/**
 * Which of the back link's labels fits its side of the bar: 0 the first (the
 * parent's name), 1 the next ("Tillbaka"), 2 none (the arrow alone). Each is
 * measured in the link's font, with the link's icon and padding as a labelled
 * link has them (an icon-only one has none, so they are kept from the first
 * measure), against the side's width, which does not depend on the label (a
 * `minmax(0, 1fr)` column), so the answer never flips back and forth. 0 until
 * measured: a hidden bar or a test has no layout, and keeps the name.
 */
function useBackLabel(cellRef: React.RefObject<HTMLDivElement | null>, labels: readonly string[]) {
  const [fitting, setFitting] = useState(0);
  const chromeRef = useRef<number | null>(null);
  const key = labels.join("\u0000");
  useLayoutEffect(() => {
    const cell = cellRef.current;
    if (!cell || typeof ResizeObserver === "undefined") return;
    const measure = () => {
      const link = cell.firstElementChild;
      if (!(link instanceof HTMLElement) || cell.clientWidth === 0) return;
      const context = document.createElement("canvas").getContext("2d");
      if (!context) return;
      const style = getComputedStyle(link);
      context.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
      const icon = link.querySelector("svg")?.getBoundingClientRect().width ?? 0;
      chromeRef.current ??=
        parseFloat(style.paddingLeft) +
        parseFloat(style.paddingRight) +
        icon +
        (parseFloat(style.columnGap) || 0);
      const chrome = chromeRef.current;
      const index = key
        .split("\u0000")
        .findIndex((label) => context.measureText(label).width + chrome <= cell.clientWidth);
      setFitting(index === -1 ? 2 : index);
    };
    // Observing reports the first size; the fonts may still swap in.
    const observer = new ResizeObserver(measure);
    observer.observe(cell);
    void document.fonts?.ready.then(measure);
    return () => observer.disconnect();
  }, [cellRef, key]);
  return fitting;
}
