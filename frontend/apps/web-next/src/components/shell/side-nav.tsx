import { MobileNav } from "@astryxdesign/core/MobileNav";
import { SideNav, SideNavRenderContext } from "@astryxdesign/core/SideNav";
import Link from "@/lib/link";
import { useTranslations } from "use-intl";
import { useEffect, useState } from "react";
import { MEDIA } from "@/lib/breakpoints";
import { useFocusRescue } from "@/lib/focus-rescue";
import { useMediaQuery } from "@astryxdesign/core/hooks";
import { cn } from "@/lib/utils";
import { AdminSections, AdminTopContent } from "./admin-nav";
import { EneoWordMark } from "./eneo-logo";
import { MainSections, MainTopContent } from "./main-nav";
import { NavFooter } from "./nav-footer";
import { AccountNavHeading, AccountNavSections } from "@/features/account/account-side-nav";
import {
  SpaceNavHeading,
  SpaceNavSections,
  SpacesListNavHeading,
  SpacesListNavSections
} from "@/features/spaces/frame/space-nav";
import { NavHeader } from "./nav-header";
import { NotificationBells } from "./notification-bells";
import type { NavVariant, SideNavKind } from "./routes";
import { DRAWER_MARKER } from "./shell-context";
import { storeSideNavCollapsed } from "./side-nav-preference";

function navLabelKey(variant: NavVariant) {
  return variant === "admin" ? "shell_administration" : "shell_nav_label";
}

export type SideNavRail = {
  /** Shown as the icon rail. */
  collapsed: boolean;
  /** The stored choice; undefined while the width decides. */
  chosen: boolean | undefined;
  /** Collapses or expands the nav and stores the choice. */
  change: (collapsed: boolean) => void;
};

/**
 * Whether the SideNav is its icon rail. The app shell owns it, so the top
 * bar's wordmark cell keeps to the SideNav's width without a CSS :has() rule.
 */
export function useSideNavRail(defaultCollapsed: boolean | undefined): SideNavRail {
  const [chosen, setChosen] = useState(defaultCollapsed);
  const isNarrow = useMediaQuery(`not all and ${MEDIA.xl}`);
  return {
    collapsed: chosen ?? isNarrow,
    chosen,
    change: (next) => {
      setChosen(next);
      storeSideNavCollapsed(next);
    }
  };
}

/**
 * The desktop SideNav (from 768 px, but not on a phone turned sideways): a
 * named `nav` landmark that collapses to an icon rail. As in the Svelte app it
 * holds the place the page is in (`sideNavKind`): a space's switcher and
 * sections, the spaces list, the account, or administration. Below 1280 px
 * (an iPad either way, a small laptop) it is the rail unless the user chose
 * otherwise, so the page keeps its room; the rail's items keep their names
 * (accessible name and tooltip). The choice is a per-browser preference
 * (`useSideNavRail`), and a stored choice wins at every width.
 */
export function DesktopSideNav({
  kind,
  navId,
  rail
}: {
  kind: SideNavKind;
  navId: string;
  rail: SideNavRail;
}) {
  const t = useTranslations();
  const { collapsed, chosen } = rail;

  // The width collapsing or expanding the nav removes whole sections. If the
  // focused link was one of them, focus goes to the toggle, which stays; focus
  // anywhere else is left alone. Read while the focused element is still in
  // the page, before this render commits.
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

  const content = SIDE_NAV_CONTENT[kind];
  return (
    <SideNav
      id={navId}
      aria-label={t(content.label)}
      collapsible={{ isCollapsed: collapsed, onCollapsedChange: rail.change, hasButton: false }}
      header={
        <div className="flex flex-col gap-1">
          <NavHeader navId={navId} />
          {content.heading}
        </div>
      }
      topContent={content.top}
      footer={<NavFooter variant={kind === "admin" ? "admin" : "main"} />}
      // 17 rem wide as in the Svelte app, 64 px as an icon rail.
      className={cn("bg-ax-surface", collapsed ? "w-16" : "w-68")}
    >
      {content.items}
    </SideNav>
  );
}

/** What each sidebar holds: its name, its heading, and its items. */
const SIDE_NAV_CONTENT: Record<
  SideNavKind,
  { label: string; heading?: React.ReactNode; top?: React.ReactNode; items: React.ReactNode }
> = {
  space: {
    label: "shell_space_nav_label",
    heading: <SpaceNavHeading />,
    items: <SpaceNavSections />
  },
  "spaces-list": {
    label: "shell_space_nav_label",
    heading: <SpacesListNavHeading />,
    items: <SpacesListNavSections />
  },
  account: {
    label: "account_and_settings",
    heading: <AccountNavHeading />,
    items: <AccountNavSections />
  },
  admin: { label: "shell_administration", top: <AdminTopContent />, items: <AdminSections /> }
};

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
