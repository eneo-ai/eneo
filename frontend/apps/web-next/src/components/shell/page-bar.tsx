"use client";

import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { ChevronLeft } from "lucide-react";
import { useTranslations } from "next-intl";
import { OWN_MOBILE_HEADER } from "./shell-context";

export type PageBarProps = {
  /** Where the back link goes: the screen the user came down from. */
  parent: { label: string; href: string };
  /**
   * The page's title, shown in the bar once the page's own h1 has scrolled
   * under it. Decoration: the h1 stays the page's heading.
   */
  title?: string;
  /** Page actions at the end of the bar. */
  actions?: React.ReactNode;
};

/**
 * The header of a pushed screen below 1024px (an admin area; later a space
 * page or an editor): a back link that names where it goes (decision 20),
 * the title once the page has scrolled, and actions. It replaces the shell's
 * top bar (`OWN_MOBILE_HEADER`), so the menu is one tap back, on the parent.
 * Render it first in main#main-content, outside the page's padding: it
 * sticks to the top of the page panel.
 */
export function PageBar({ parent, title, actions }: PageBarProps) {
  const t = useTranslations();
  return (
    // The title is centred while it fits; the back link's name never gives way to it.
    <div
      {...OWN_MOBILE_HEADER}
      // main#main-content keeps focused and scrolled-to content clear of it (app-shell.tsx).
      data-page-bar=""
      className="bg-ax-surface border-ax-border sticky top-0 z-10 grid h-14 shrink-0 grid-cols-[minmax(max-content,1fr)_minmax(0,auto)_minmax(max-content,1fr)] items-center gap-1 border-b px-1.5 lg:hidden"
    >
      <Button
        href={parent.href}
        variant="ghost"
        size="lg"
        icon={<Icon icon={ChevronLeft} />}
        label={parent.label}
        aria-label={t("shell_back_to", { name: parent.label })}
        className="text-ax-text-accent justify-self-start"
      />
      <span
        aria-hidden="true"
        className="page-bar-title truncate text-center text-sm font-semibold"
      >
        {title}
      </span>
      <div className="flex items-center justify-self-end">{actions}</div>
    </div>
  );
}
