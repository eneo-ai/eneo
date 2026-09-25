"use client";

import {
  AppShellMobileContext,
  type AppShellMobileContextValue
} from "@astryxdesign/core/AppShell";
import { useHotkeys, useMediaQuery } from "@astryxdesign/core/hooks";
import dynamic from "next/dynamic";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { Fragment, useCallback, useEffect, useId, useMemo, useState } from "react";
import { CreateSpaceDialog } from "@/features/spaces/create-space-dialog";
import { MobileTopBar } from "./mobile-top-bar";
import { isAdminRoute, isChatRoute, OPEN_NAV_EVENT, type NavVariant } from "./routes";
import { isOtherDialogOpen, ShellContext, type ShellContextValue } from "./shell-context";
import { DesktopSideNav, MobileNavDrawer } from "./side-nav";
import { usePageRemount } from "./use-page-remount";

// Loaded the first time the palette opens: nothing of it ships with page loads.
const ShellCommandPalette = dynamic(() => import("./command-palette"), { ssr: false });

/** Below Tailwind's `md` breakpoint the SideNav becomes a drawer. */
const MOBILE_QUERY = "(width < 48rem)";

/**
 * The app frame: skip link (first tab stop), the SideNav (desktop) or the top
 * bar + drawer (phones), and the page panel `main#main-content` that pages
 * scroll inside. Also hosts the ⌘K palette and the "Skapa yta" dialog.
 *
 * Not Astryx AppShell: it fixes its own main landmark id and skip link, and
 * web-next's contract is `main#main-content` (ACCESSIBILITY.md rule 1,
 * tests/a11y.spec.ts). Its parts (SideNav, MobileNav, MobileNavToggle and the
 * AppShell mobile context they share) are used as they are.
 *
 * Contract with the chat: chat routes render their own compact mobile header
 * (no top bar here) and open the drawer with
 * `window.dispatchEvent(new CustomEvent("eneo:open-nav"))`.
 */
export function AppShellFrame({ children }: { children: React.ReactNode }) {
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
  const { pageKey, prepareNavigation } = usePageRemount();

  // Navigating (from any link, not only nav items) or leaving the phone
  // layout closes the drawer.
  const [seen, setSeen] = useState({ pathname, isMobile });
  if (seen.pathname !== pathname || seen.isMobile !== isMobile) {
    setSeen({ pathname, isMobile });
    setNavOpen(false);
  }
  const drawerOpen = isMobile && navOpen;

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
  const shell = useMemo<ShellContextValue>(
    () => ({ openPalette, openCreateSpace, prepareNavigation }),
    [openPalette, openCreateSpace, prepareNavigation]
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
      <AppShellMobileContext value={mobileNav}>
        <div className="bg-ax-body flex h-svh flex-col md:flex-row md:gap-2 md:p-2">
          <a
            href="#main-content"
            className="focus:bg-ax-surface focus:text-ax-text focus:rounded-ax-element focus:border-ax-border-strong focus:shadow-ax-med focus-visible:outline-ring sr-only focus:not-sr-only focus:absolute focus:top-3 focus:left-3 focus:z-50 focus:border focus:px-3 focus:py-2 focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            {t("skip_to_content")}
          </a>
          {!isChatRoute(pathname) && <MobileTopBar />}
          <div className="hidden min-h-0 shrink-0 md:flex md:flex-col">
            <DesktopSideNav variant={variant} navId={navId} />
          </div>
          {/* tabIndex -1: the skip link moves focus here, not just the scroll
              position (WCAG 2.4.1); tests/a11y.spec.ts checks it. */}
          <main
            id="main-content"
            tabIndex={-1}
            className="bg-ax-surface md:rounded-ax-page md:shadow-ax-low flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto focus:outline-none"
          >
            <Fragment key={pageKey}>{children}</Fragment>
          </main>
          {isMobile && (
            <MobileNavDrawer variant={variant} isOpen={drawerOpen} onOpenChange={setNavOpen} />
          )}
          {paletteMounted && (
            <ShellCommandPalette
              isOpen={paletteOpen}
              onOpenChange={setPaletteOpen}
              onCreateSpace={openCreateSpace}
            />
          )}
          <CreateSpaceDialog open={createSpaceOpen} onOpenChange={setCreateSpaceOpen} />
        </div>
      </AppShellMobileContext>
    </ShellContext>
  );
}
