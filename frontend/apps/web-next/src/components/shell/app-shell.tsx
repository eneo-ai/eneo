"use client";

import {
  AppShellMobileContext,
  type AppShellMobileContextValue
} from "@astryxdesign/core/AppShell";
import { useHotkeys, useMediaQuery } from "@astryxdesign/core/hooks";
import dynamic from "next/dynamic";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { CreateSpaceDialog } from "@/features/spaces/create-space-dialog";
import { ConnectionAnnouncer, ConnectionBanner } from "./connection-banner";
import { MobileTopBar } from "./mobile-top-bar";
import { isAdminRoute, OPEN_NAV_EVENT, type NavVariant } from "./routes";
import { isOtherDialogOpen, ShellContext, type ShellContextValue } from "./shell-context";
import { DesktopSideNav, MobileNavDrawer } from "./side-nav";

// Loaded the first time the palette opens: nothing of it ships with page loads.
const ShellCommandPalette = dynamic(() => import("./command-palette"), { ssr: false });

/**
 * Below Tailwind's `lg` breakpoint (phones and an iPad held upright) the
 * SideNav becomes a drawer. The markup mirrors it with `lg:` variants.
 */
const MOBILE_QUERY = "(width < 64rem)";

/**
 * The app frame: skip link (first tab stop), the SideNav (from 1024 px) or
 * the top bar + drawer (phones and iPads held upright), and the page panel
 * `main#main-content` that pages scroll inside. Also hosts the ⌘K palette
 * and the "Skapa yta" dialog.
 *
 * Not Astryx AppShell: it fixes its own main landmark id and skip link, and
 * web-next's contract is `main#main-content` (ACCESSIBILITY.md rule 1,
 * tests/a11y.spec.ts). Its parts (SideNav, MobileNav, MobileNavToggle and the
 * AppShell mobile context they share) are used as they are.
 *
 * Contract with the chat and pushed screens: their header (the chat's, a
 * `PageBar`) carries `OWN_MOBILE_HEADER` and the top bar gives way to it in
 * CSS; the chat's opens the drawer by dispatching `OPEN_NAV_EVENT` on the
 * window.
 *
 * Nothing above the page may change after hydration on phones: a context
 * update above a page React has not hydrated yet (its code is still loading)
 * replaces the server-rendered page with its loading state. So the
 * mobile-nav context, whose `isMobile` the server cannot know, wraps the
 * navigation only, and the top bar's visibility is CSS, not state.
 */
export function AppShellFrame({
  children,
  sideNavCollapsed = false
}: {
  children: React.ReactNode;
  /** The stored SideNav preference, read from its cookie by the server layout. */
  sideNavCollapsed?: boolean;
}) {
  const t = useTranslations();
  const pathname = usePathname();
  const isMobile = useMediaQuery(MOBILE_QUERY);
  const navId = useId();
  const drawerId = useId();
  const variant: NavVariant = isAdminRoute(pathname) ? "admin" : "main";

  const [navOpen, setNavOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [paletteMounted, setPaletteMounted] = useState(false);
  const [createSpaceOpen, setCreateSpaceOpen] = useState(false);

  // Navigating (from any link, not only nav items) or leaving the phone
  // layout closes the drawer. A palette result can stay on the same path
  // (another conversation): the palette closes the drawer itself (onNavigate).
  const [seen, setSeen] = useState({ pathname, isMobile });
  if (seen.pathname !== pathname || seen.isMobile !== isMobile) {
    setSeen({ pathname, isMobile });
    setNavOpen(false);
  }
  const drawerOpen = isMobile && navOpen;

  // Widening past the phone layout (an iPad turned sideways) unmounts the
  // drawer or hides the top bar, and with them the focused element: the page
  // takes the focus instead of the document body.
  const mainRef = useRef<HTMLElement>(null);
  const wasMobile = useRef(isMobile);
  useEffect(() => {
    if (wasMobile.current && !isMobile && document.activeElement === document.body) {
      mainRef.current?.focus({ preventScroll: true });
    }
    wasMobile.current = isMobile;
  }, [isMobile]);

  useEffect(() => {
    if (!isMobile) return;
    const openFromChat = () => setNavOpen(true);
    window.addEventListener(OPEN_NAV_EVENT, openFromChat);
    return () => window.removeEventListener(OPEN_NAV_EVENT, openFromChat);
  }, [isMobile]);

  const openPalette = useCallback(() => {
    setPaletteMounted(true);
    setPaletteOpen(true);
  }, []);
  const openFromShortcut = () => {
    if (!isOtherDialogOpen()) openPalette();
  };
  const closePalette = () => setPaletteOpen(false);
  // ⌘K and Ctrl+K toggle the palette. useHotkeys leaves text fields alone,
  // except for closing the palette from its own search field.
  useHotkeys([
    { keys: "meta+k", onPress: openFromShortcut, isDisabled: paletteOpen },
    { keys: "ctrl+k", onPress: openFromShortcut, isDisabled: paletteOpen },
    { keys: "meta+k", onPress: closePalette, isDisabled: !paletteOpen, allowInInputs: true },
    { keys: "ctrl+k", onPress: closePalette, isDisabled: !paletteOpen, allowInInputs: true }
  ]);

  const openCreateSpace = useCallback(() => setCreateSpaceOpen(true), []);
  const closeNav = useCallback(() => setNavOpen(false), []);
  const shell = useMemo<ShellContextValue>(
    () => ({ openPalette, openCreateSpace }),
    [openPalette, openCreateSpace]
  );

  // Astryx's mobile-nav context: MobileNavToggle opens the drawer, SideNavItems
  // in it close it, and SideNav's collapse control stays away on phones.
  const mobileNav = useMemo<AppShellMobileContextValue>(
    () => ({
      isMobile,
      isMobileNavOpen: drawerOpen,
      mobileNavId: drawerId,
      toggleMobileNav: () => setNavOpen((open) => !open),
      openMobileNav: () => setNavOpen(true),
      closeMobileNav: () => setNavOpen(false),
      isMobileNavEnabled: isMobile,
      hasAutoToggle: false
    }),
    [isMobile, drawerOpen, drawerId]
  );

  return (
    <ShellContext value={shell}>
      {/* The page runs under the notch and the home indicator
          (viewport-fit=cover): the frame keeps the top and the sides clear,
          main#main-content the bottom. On phones the surface fills the
          frame, so the strip under the status bar continues the top bar;
          from lg the page panel floats on the body colour. group/shell: the
          top bar hides while the page has its own header. */}
      <div className="group/shell bg-ax-surface lg:bg-ax-body flex h-svh flex-col pt-[env(safe-area-inset-top,0px)] pr-[env(safe-area-inset-right,0px)] pl-[env(safe-area-inset-left,0px)] lg:flex-row lg:gap-2 lg:pt-[max(0.5rem,env(safe-area-inset-top,0px))] lg:pr-[max(0.5rem,env(safe-area-inset-right,0px))] lg:pb-[max(0.5rem,env(safe-area-inset-bottom,0px))] lg:pl-[max(0.5rem,env(safe-area-inset-left,0px))]">
        <a
          href="#main-content"
          className="focus:bg-ax-surface focus:text-ax-text focus:rounded-ax-element focus:border-ax-border-strong focus:shadow-ax-med focus-visible:outline-ring sr-only focus:not-sr-only focus:absolute focus:top-3 focus:left-3 focus:z-50 focus:border focus:px-3 focus:py-2 focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          {t("skip_to_content")}
        </a>
        <AppShellMobileContext value={mobileNav}>
          <MobileTopBar />
          <div className="hidden min-h-0 shrink-0 lg:flex lg:flex-col">
            <DesktopSideNav variant={variant} navId={navId} defaultCollapsed={sideNavCollapsed} />
          </div>
        </AppShellMobileContext>
        {/* tabIndex -1: the skip link moves focus here, not just the scroll
            position (WCAG 2.4.1); tests/a11y.spec.ts checks it. relative:
            the panel contains what is absolutely positioned in it (visually
            hidden text), which otherwise escapes its scroll box and makes
            the document taller, so the whole shell scrolls. scroll-pt-14:
            while a PageBar sticks to its top, focus and scrollIntoView stop
            below the bar instead of under it (WCAG 2.4.11). The bottom
            likewise keeps clear of a phone's docked action bar
            (DockedActions), which it reserves room for. */}
        <main
          ref={mainRef}
          id="main-content"
          tabIndex={-1}
          className="bg-ax-surface lg:rounded-ax-page lg:shadow-ax-low relative flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto pb-[env(safe-area-inset-bottom,0px)] focus:outline-none max-lg:has-[[data-page-bar]]:scroll-pt-14 max-md:has-[[data-docked-actions]]:scroll-pb-[var(--docked-actions-height,calc(4.5rem+env(safe-area-inset-bottom,0px)))] max-md:has-[[data-docked-actions]]:pb-[var(--docked-actions-height,calc(4.5rem+env(safe-area-inset-bottom,0px)))] max-md:has-[[data-phone-page-bar]]:scroll-pt-14 lg:pb-0"
        >
          {/* Under the top bar; a page with its own header shows its own
              under that header, and this one gives way. */}
          <ConnectionBanner className="group-has-[[data-own-mobile-header]]/shell:hidden max-md:group-has-[[data-own-phone-header]]/shell:hidden" />
          {children}
        </main>
        <ConnectionAnnouncer />
        {isMobile && (
          <AppShellMobileContext value={mobileNav}>
            <MobileNavDrawer variant={variant} isOpen={drawerOpen} onOpenChange={setNavOpen} />
          </AppShellMobileContext>
        )}
        {paletteMounted && (
          <ShellCommandPalette
            isOpen={paletteOpen}
            onOpenChange={setPaletteOpen}
            onCreateSpace={openCreateSpace}
            onNavigate={closeNav}
          />
        )}
        <CreateSpaceDialog open={createSpaceOpen} onOpenChange={setCreateSpaceOpen} />
      </div>
    </ShellContext>
  );
}
