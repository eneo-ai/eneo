import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { ChevronLeft } from "lucide-react";
import { useTranslations } from "use-intl";
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
   * Where the bar is shown: below `lg` (1024 px: Konto's pushed screens) or
   * on a `phone`'s layout (below 768 px, or a phone turned sideways: a space,
   * an admin area, which tablets show with breadcrumbs beside the side
   * navigation).
   */
  until?: "lg" | "phone";
};

/**
 * The header of a pushed screen (an admin area, a space, an editor's section,
 * Konto's pages): a back link that names where it goes (decision 20), the
 * title once the page has scrolled, and actions. On a phone it replaces the
 * shell's top bar (`OWN_MOBILE_HEADER`), so the menu is one tap back, on the
 * parent.
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
  const phone = until === "phone";
  return (
    <>
      {/* The back link always names the parent, on every sibling page alike.
          It goes before the title, which is decoration and takes the room
          left over; a name longer than the bar ends in an ellipsis, and the
          link's accessible name keeps all of it. */}
      <div
        {...(phone ? OWN_PHONE_HEADER : OWN_MOBILE_HEADER)}
        // main#main-content keeps focused and scrolled-to content clear of it (app-shell.tsx).
        {...(phone ? { "data-phone-page-bar": "" } : { "data-page-bar": "" })}
        className={cn(
          // The back side keeps at least 44 px (2.75rem) and grows to its whole name; the
          // title column truncates and gives way, and the actions keep their size.
          "bg-ax-surface border-ax-border sticky top-0 z-10 grid h-14 shrink-0 grid-cols-[minmax(2.75rem,max-content)_minmax(0,1fr)_max-content] items-center gap-1 border-b px-1.5",
          phone ? "wide:hidden" : "lg:hidden"
        )}
      >
        <div className="min-w-0">
          <Button
            href={parent.href}
            {...(parent.onClick ? { onClick: parent.onClick, as: SamePageLink } : {})}
            variant="ghost"
            size="lg"
            icon={<Icon icon={ChevronLeft} />}
            label={parent.label}
            aria-label={t("shell_back_to", { name: parent.label })}
            className="text-ax-text-accent max-w-full min-w-0"
          />
        </div>
        <span
          aria-hidden="true"
          className={cn(
            "truncate text-center text-sm font-semibold",
            !isTitleShown && "page-bar-title"
          )}
        >
          {title}
        </span>
        <div className="flex items-center justify-self-end">{actions}</div>
      </div>
      {/* Under the bar, not in it: the bar is hidden from 1024px, the banner is
          not. Where the bar is for phones only, the shell's banner is back
          where the layout is not a phone's, and this one gives way to it. */}
      <ConnectionBanner className={phone ? "wide:hidden" : undefined} />
    </>
  );
}
