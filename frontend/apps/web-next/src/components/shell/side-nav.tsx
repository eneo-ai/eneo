import { MobileNav } from "@astryxdesign/core/MobileNav";
import { SideNav, SideNavRenderContext } from "@astryxdesign/core/SideNav";
import Link from "@/lib/link";
import { useTranslations } from "use-intl";
import { useEffect, useState } from "react";
import { MEDIA } from "@/lib/breakpoints";
import { useFocusRescue } from "@/lib/focus-rescue";
import { useMediaQuery } from "@astryxdesign/core/hooks";
import { cn } from "@/lib/utils";
import { useTouchTablet } from "@/lib/hooks/use-media-match";
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
  /** The choice that holds at this width; undefined while the width decides. */
  chosen: boolean | undefined;
  /** Collapses or expands the nav and stores the choice. */
  change: (collapsed: boolean) => void;
};

/**
 * Whether the SideNav is its icon rail. The app shell owns it, so the top
 * bar's wordmark cell keeps to the SideNav's width without a CSS :has() rule.
 *
 * A toggle pressed during this visit holds at every width. The stored choice
 * (`stored`, from the cookie) holds from `lg` (1024 px) only: below it an
 * open sidebar takes over a third of an upright iPad, so a later visit starts
 * there as the rail again. With neither, the width decides (the rail below
 * 1280 px).
 */
export function useSideNavRail(stored: boolean | undefined): SideNavRail {
  const [pressed, setPressed] = useState<boolean>();
  const belowLg = useMediaQuery(`not all and ${MEDIA.lg}`);
  const isNarrow = useMediaQuery(`not all and ${MEDIA.xl}`);
  const chosen = pressed ?? (belowLg ? undefined : stored);
  return {
    collapsed: chosen ?? isNarrow,
    chosen,
    change: (next) => {
      setPressed(next);
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
 * (`useSideNavRail`) that holds from 1024 px; below that only a toggle
 * pressed during this visit opens the nav.
 *
 * A tablet (`useTouchTablet`) has no top bar and keeps the navigation built
 * for touch instead, on every page: the wordmark and the bells, Ny
 * konversation, Sök, every space, Senaste, Organisation, Administration and
 * the profile; administration's own navigation under /admin.
 */
export function DesktopSideNav({
  kind,
  navId,
  rail
}: {
  /** The place the page is in; null where a computer shows no sidebar. */
  kind: SideNavKind | null;
  navId: string;
  rail: SideNavRail;
}) {
  const t = useTranslations();
  const tablet = useTouchTablet();
  const variant: NavVariant = kind === "admin" ? "admin" : "main";
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

  const content = tablet || kind === null ? TABLET_NAV_CONTENT[variant] : SIDE_NAV_CONTENT[kind];
  // A row of its own for one button pushes the place's name down; the rail stacks them.
  const toggleBesideHeading = !tablet && !collapsed && Boolean(content.heading);
  return (
    <SideNav
      id={navId}
      aria-label={t(content.label)}
      collapsible={{ isCollapsed: collapsed, onCollapsedChange: rail.change, hasButton: false }}
      header={
        <div className="relative flex flex-col gap-1">
          {tablet && <NavHeader navId={navId} withBrand />}
          {content.heading && (
            <div className={cn(toggleBesideHeading && "pe-9")}>{content.heading}</div>
          )}
          {/* After the heading, so Tab meets the switcher and then the toggle at the
              row's end; in the rail it stands under the chip. */}
          {!tablet && <NavHeader navId={navId} besideHeading={toggleBesideHeading} />}
        </div>
      }
      topContent={content.top}
      footer={<NavFooter variant={variant} />}
      className={cn(
        // Astryx draws a row's icon at 16 px in a lighter grey than its label; beside
        // a 14 px label that reads thin. The Svelte app's are larger and take the label's colour.
        "[&_.astryx-side-nav-item>svg]:size-5 [&_.astryx-side-nav-item>svg]:[stroke-width:1.75]",
        "[&_.astryx-side-nav-item:not([data-selected=selected])>svg]:text-ax-text-secondary",
        tablet
          ? // ≈248 px wide, 64 px as an icon rail; the app body shows through.
            cn("bg-ax-body", collapsed ? "w-16" : "w-62")
          : // 17 rem wide as in the Svelte app, 64 px as an icon rail.
            cn("bg-ax-surface", collapsed ? "w-16" : "w-68")
      )}
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

/** A tablet's navigation, built for touch (#1328): the same as the phone's drawer. */
const TABLET_NAV_CONTENT: Record<
  NavVariant,
  { label: string; heading?: React.ReactNode; top?: React.ReactNode; items: React.ReactNode }
> = {
  main: { label: "shell_nav_label", top: <MainTopContent />, items: <MainSections /> },
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
