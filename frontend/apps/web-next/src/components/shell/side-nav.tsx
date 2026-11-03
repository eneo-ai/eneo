import { MobileNav } from "@astryxdesign/core/MobileNav";
import { SideNav, SideNavRenderContext } from "@astryxdesign/core/SideNav";
import Link from "@/lib/link";
import { useTranslations } from "use-intl";
import { useEffect, useState } from "react";
import { MEDIA } from "@/lib/breakpoints";
import { useFocusRescue } from "@/lib/focus-rescue";
import { useMediaMatch } from "@/lib/hooks/use-media-match";
import { cn } from "@/lib/utils";
import { AdminSections, AdminTopContent } from "./admin-nav";
import { EneoWordMark } from "./eneo-logo";
import { MainSections, MainTopContent } from "./main-nav";
import { NavFooter } from "./nav-footer";
import { NavHeader } from "./nav-header";
import { NotificationBells } from "./notification-bells";
import type { NavVariant } from "./routes";
import { DRAWER_MARKER } from "./shell-context";
import { storeSideNavCollapsed } from "./side-nav-preference";

function navLabelKey(variant: NavVariant) {
  return variant === "admin" ? "shell_administration" : "shell_nav_label";
}

/**
 * The desktop SideNav (from 768 px, but not on a phone turned sideways): a
 * named `nav` landmark that collapses to an icon rail. Below 1280 px (an iPad either way, a small laptop) it is the rail
 * unless the user chose otherwise, so the page keeps its room; the rail's
 * items keep their names (accessible name and tooltip). The choice is a
 * per-browser preference: the layout reads it (`defaultCollapsed`, undefined
 * when none was made), a change stores it, and a stored choice wins at every
 * width.
 */
export function DesktopSideNav({
  variant,
  navId,
  defaultCollapsed
}: {
  variant: NavVariant;
  navId: string;
  defaultCollapsed?: boolean;
}) {
  const t = useTranslations();
  const [chosen, setChosen] = useState(defaultCollapsed);
  const isNarrow = useMediaMatch(`not all and ${MEDIA.xl}`);
  const collapsed = chosen ?? isNarrow;

  // The width collapsing or expanding the nav removes whole sections (Senaste
  // in the icon rail). If the focused link was one of them, focus goes to the
  // toggle, which stays; focus anywhere else is left alone. Read while the
  // focused element is still in the page, before this render commits.
  const rescueFocus = useFocusRescue();
  const [shown, setShown] = useState({ collapsed, focusInNav: false });
  if (shown.collapsed !== collapsed) {
    const focusInNav =
      chosen === undefined && !!document.getElementById(navId)?.contains(document.activeElement);
    setShown({ collapsed, focusInNav });
  }
  useEffect(() => {
    if (!shown.focusInNav) return;
    rescueFocus(
      () =>
        document.getElementById(navId)?.querySelector<HTMLElement>(`[aria-controls="${navId}"]`) ??
        null
    );
  }, [shown, navId, rescueFocus]);

  function changeCollapsed(next: boolean) {
    setChosen(next);
    storeSideNavCollapsed(next);
  }

  return (
    <SideNav
      id={navId}
      aria-label={t(navLabelKey(variant))}
      collapsible={{ isCollapsed: collapsed, onCollapsedChange: changeCollapsed, hasButton: false }}
      header={<NavHeader navId={navId} />}
      topContent={variant === "admin" ? <AdminTopContent /> : <MainTopContent />}
      footer={<NavFooter variant={variant} />}
      // ≈248 px wide (the design), 64 px as an icon rail; the app body shows through.
      className={cn("bg-ax-body", collapsed ? "w-16" : "w-62")}
    >
      {variant === "admin" ? <AdminSections /> : <MainSections />}
    </SideNav>
  );
}

/**
 * Phones, held either way: the same navigation in an Astryx MobileNav drawer (a modal
 * dialog: focus moves in, Escape and the close button close it, focus returns
 * to the button that opened it). Items close the drawer when activated.
 */
export function MobileNavDrawer({
  variant,
  isOpen,
  onOpenChange
}: {
  variant: NavVariant;
  isOpen: boolean;
  onOpenChange: (isOpen: boolean) => void;
}) {
  const t = useTranslations();

  return (
    <MobileNav
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      side="start"
      width={320}
      label={t("shell_menu_label")}
      header={
        <div className="flex min-w-0 flex-1 items-center justify-between gap-1">
          <Link
            href="/"
            aria-label={t("shell_home_link")}
            onClick={() => onOpenChange(false)}
            className="rounded-ax-inner focus-visible:outline-ring ms-2 flex h-11 items-center focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            <EneoWordMark className="h-5 w-auto" />
          </Link>
          <div className="flex items-center">
            <NotificationBells />
          </div>
        </div>
      }
      {...{ [DRAWER_MARKER]: "" }}
    >
      <SideNavRenderContext value="drawer-content">
        <nav aria-label={t(navLabelKey(variant))} className="flex min-h-full flex-col gap-4">
          {variant === "admin" ? <AdminTopContent /> : <MainTopContent />}
          {variant === "admin" ? <AdminSections /> : <MainSections />}
          <div className="mt-auto">
            <NavFooter variant={variant} />
          </div>
        </nav>
      </SideNavRenderContext>
    </MobileNav>
  );
}
