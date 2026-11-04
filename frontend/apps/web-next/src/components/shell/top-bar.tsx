import { Icon } from "@astryxdesign/core/Icon";
import { IconButton } from "@astryxdesign/core/IconButton";
import { TopNav, TopNavItem } from "@astryxdesign/core/TopNav";
import { ArrowUpToLine, Search } from "lucide-react";
import Link from "@/lib/link";
import { usePathname } from "@/lib/navigation";
import { useTranslations } from "use-intl";
import { useEffect, useRef, useState } from "react";
import { useAppContext } from "@/components/providers/app-context";
import { cn } from "@/lib/utils";
import { EneoIcon, EneoWordMark } from "./eneo-logo";
import { NotificationBells } from "./notification-bells";
import { ProfileMenu } from "./profile-menu";
import { areaOf, type Area } from "./routes";
import { useShell } from "./shell-context";

/**
 * The desktop top bar, as in the Svelte app (`(app)/+layout.svelte`): the
 * wordmark in a cell as wide as the SideNav, the areas Personligt, Delat and
 * (admins) Organisation, then search, Administratör, the bells and the
 * profile. The areas are links, not tabs: each is a route.
 *
 * Like Svelte's, the bar can be hidden from the arrow on the wordmark cell and
 * comes back when the pointer reaches the top edge. Hidden, it leaves the tab
 * order, and a "Visa sidhuvudet" button (visible on focus) brings it back
 * from the keyboard (WCAG 2.1.1); each button hands focus to the other.
 */
export function TopBar({
  railCollapsed = false,
  className
}: {
  /** The SideNav below is its icon rail: the wordmark cell narrows to it. */
  railCollapsed?: boolean;
  className?: string;
}) {
  const t = useTranslations();
  const { can } = useAppContext();
  const { openPalette } = useShell();
  const area = areaOf(usePathname());
  const isAdmin = can("admin");
  // The area holds the current page but is not it: aria-current="true", not
  // "page" (Astryx's default), so the page's own link stays the one "page".
  const current = (of: Area) =>
    area === of ? { isSelected: true, "aria-current": "true" as const } : { isSelected: false };
  const [shown, setShown] = useState(true);
  const showRef = useRef<HTMLButtonElement>(null);
  const hideRef = useRef<HTMLButtonElement>(null);
  const homeRef = useRef<HTMLAnchorElement>(null);
  // Set by the buttons, not by the pointer: only a keyboard or click toggle moves focus.
  const handOff = useRef(false);

  useEffect(() => {
    if (!handOff.current) return;
    handOff.current = false;
    // The pressed button is gone: focus goes to its counterpart.
    // In the icon rail there is no hide button: the home link takes focus.
    (shown ? (hideRef.current ?? homeRef.current) : showRef.current)?.focus();
  }, [shown]);

  function toggle(next: boolean) {
    handOff.current = true;
    setShown(next);
  }

  if (!shown) {
    return (
      <div className={cn("relative h-0", className)}>
        <div
          data-top-bar-reveal=""
          aria-hidden="true"
          className="fixed inset-x-0 top-0 z-50 h-3"
          onPointerEnter={() => setShown(true)}
        />
        <button
          ref={showRef}
          type="button"
          onClick={() => toggle(true)}
          className="focus:bg-ax-surface focus:text-ax-text focus:rounded-ax-element focus:border-ax-border-strong focus:shadow-ax-med focus-visible:outline-ring sr-only focus:not-sr-only focus:absolute focus:top-1 focus:left-3 focus:z-50 focus:border focus:px-3 focus:py-2 focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          {t("show_header")}
        </button>
      </div>
    );
  }

  return (
    <header
      className={cn(
        "bg-ax-body border-ax-border flex h-13 shrink-0 items-stretch border-b",
        className
      )}
    >
      {/* As wide as the SideNav below it, its icon rail included. */}
      <div
        className={cn(
          "group/brand border-ax-border flex shrink-0 items-center border-e",
          railCollapsed ? "w-16 justify-center" : "w-68 justify-between ps-4 pe-2"
        )}
      >
        <Link
          ref={homeRef}
          href="/"
          aria-label={t("shell_home_link")}
          className="rounded-ax-inner focus-visible:outline-ring flex h-8 items-center justify-center focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:h-11 pointer-coarse:min-w-11"
        >
          {railCollapsed ? (
            <EneoIcon className="h-6 w-auto" />
          ) : (
            <EneoWordMark className="h-5 w-auto" />
          )}
        </Link>
        {/* The icon rail has room for the mark only. */}
        {railCollapsed ? null : (
          <IconButton
            ref={hideRef}
            variant="ghost"
            icon={<Icon icon={ArrowUpToLine} />}
            label={t("hide_header")}
            tooltip={t("hide_header")}
            onClick={() => toggle(false)}
            // Shown on hover; a touch screen has none, so it stays in sight there.
            className="opacity-0 group-hover/brand:opacity-100 focus-visible:opacity-100 pointer-coarse:opacity-100"
          />
        )}
      </div>
      <TopNav
        label={t("shell_top_nav_label")}
        className="min-w-0 px-3"
        startContent={
          <>
            <TopNavItem
              label={t("personal")}
              href="/spaces/personal/chat"
              {...current("personal")}
            />
            <TopNavItem label={t("shell_area_shared")} href="/spaces/list" {...current("shared")} />
            {isAdmin && (
              <TopNavItem
                label={t("organization")}
                href="/spaces/organization/knowledge"
                {...current("organization")}
              />
            )}
          </>
        }
        endContent={
          <>
            <IconButton
              variant="ghost"
              icon={<Icon icon={Search} />}
              label={t("search")}
              tooltip={t("search")}
              aria-keyshortcuts="Meta+K Control+K"
              onClick={() => openPalette()}
            />
            {isAdmin && <TopNavItem label={t("admin")} href="/admin" {...current("admin")} />}
            <div className="ms-2 flex items-center gap-1">
              <NotificationBells />
              <ProfileMenu inTopBar />
            </div>
          </>
        }
      />
    </header>
  );
}
