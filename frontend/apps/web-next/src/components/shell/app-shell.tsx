"use client";

import {
  AppShellMobileContext,
  type AppShellMobileContextValue
} from "@astryxdesign/core/AppShell";
import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Menu, SquarePen } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Fragment, useCallback, useEffect, useId, useMemo, useState } from "react";
import { ExpiringKeysNotification } from "@/features/api-keys/expiring-keys-notification";
import { JobIndicator } from "@/features/jobs/job-indicator";
import { CreateSpaceDialog } from "./create-space-dialog";
import { EneoWordMark } from "./eneo-logo";
import { isAdminRoute, isChatRoute, NEW_CONVERSATION_HREF, OPEN_NAV_EVENT } from "./routes";
import { ShellContext, usePaletteShortcut, type ShellContextValue } from "./shell-context";
import { isMobileViewport, useIsMobile } from "./shell-state";
import { DesktopSideNav, MobileNavDrawer, type NavVariant } from "./side-nav";

// Loaded the first time the palette opens: nothing of it ships with page loads.
const ShellCommandPalette = dynamic(() => import("./command-palette"), { ssr: false });

/** Phone layouts outside the chat: menu, Eneo and "Ny konversation" (44 px targets). */
function MobileTopBar({
  isNavOpen,
  drawerId,
  onOpenNav
}: {
  isNavOpen: boolean;
  drawerId: string | undefined;
  onOpenNav: () => void;
}) {
  const t = useTranslations();
  return (
    <header className="bg-ax-surface border-ax-border flex h-14 shrink-0 items-center gap-1 border-b px-1.5 md:hidden">
      <IconButton
        variant="ghost"
        size="lg"
        icon={<Icon icon={Menu} />}
        label={t("shell_open_menu")}
        aria-haspopup="dialog"
        aria-expanded={isNavOpen}
        aria-controls={drawerId}
        onClick={onOpenNav}
        className="size-11"
      />
      <Link
        href="/"
        aria-label={t("shell_home_link")}
        className="rounded-ax-inner focus-visible:outline-ring flex h-11 items-center px-1 focus-visible:outline-2 focus-visible:outline-offset-2"
      >
        <EneoWordMark decorative className="h-5 w-auto" />
      </Link>
      <div className="flex-1" />
      <div className="flex items-center pointer-coarse:[&_button]:size-11">
        <JobIndicator />
        <ExpiringKeysNotification />
      </div>
      <Button
        href={NEW_CONVERSATION_HREF}
        variant="ghost"
        size="lg"
        isIconOnly
        icon={<Icon icon={SquarePen} />}
        label={t("new_conversation")}
        className="size-11"
      />
    </header>
  );
}

/**
 * Next keeps a page mounted when only its search params change, and the chat
 * keeps its conversation in state. So when a shell link (Senaste, Ny
 * konversation, the palette) opens another conversation on the page that is
 * already showing, the page is remounted once the URL has arrived and starts
 * from it. Other query changes (the chat's own URL updates) never remount.
 */
function usePageRemount() {
  const pathname = usePathname();
  const search = useSearchParams().toString();
  const url = search ? `${pathname}?${search}` : pathname;
  const [state, setState] = useState<{ url: string; pending: string | null; key: number }>({
    url,
    pending: null,
    key: 0
  });
  if (state.url !== url) {
    setState({ url, pending: null, key: state.pending === url ? state.key + 1 : state.key });
  }

  const prepareNavigation = useCallback((href: string) => {
    const target = new URL(href, window.location.href);
    const next = target.pathname + target.search;
    const current = window.location.pathname + window.location.search;
    if (target.pathname !== window.location.pathname || next === current) return;
    setState((previous) => ({ ...previous, pending: next }));
  }, []);

  return { pageKey: state.key, prepareNavigation };
}

/**
 * The app frame: skip link (first tab stop), the SideNav (desktop) or the top
 * bar + drawer (phones), and the page panel `main#main-content` that pages
 * scroll inside. Also hosts the ⌘K palette and the "Skapa yta" dialog.
 *
 * Contract with the chat: chat routes render their own compact mobile header
 * (no top bar here) and open the drawer with
 * `window.dispatchEvent(new CustomEvent("eneo:open-nav"))`.
 */
export function AppShellFrame({ children }: { children: React.ReactNode }) {
  const t = useTranslations();
  const pathname = usePathname();
  const isMobile = useIsMobile();
  const navId = useId();
  const drawerId = useId();
  const variant: NavVariant = isAdminRoute(pathname) ? "admin" : "main";

  const [navOpen, setNavOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [paletteMounted, setPaletteMounted] = useState(false);
  const [createSpaceOpen, setCreateSpaceOpen] = useState(false);

  // Navigating (from any link, not only nav items) or leaving the phone
  // layout closes the drawer.
  const [seen, setSeen] = useState({ pathname, isMobile });
  if (seen.pathname !== pathname || seen.isMobile !== isMobile) {
    setSeen({ pathname, isMobile });
    setNavOpen(false);
  }
  const drawerOpen = isMobile && navOpen;

  useEffect(() => {
    function openFromChat() {
      if (isMobileViewport()) setNavOpen(true);
    }
    window.addEventListener(OPEN_NAV_EVENT, openFromChat);
    return () => window.removeEventListener(OPEN_NAV_EVENT, openFromChat);
  }, []);

  const openPalette = useCallback(() => {
    setPaletteMounted(true);
    setPaletteOpen(true);
  }, []);
  const togglePalette = useCallback(() => {
    setPaletteMounted(true);
    setPaletteOpen((open) => !open);
  }, []);
  usePaletteShortcut(paletteOpen, togglePalette);

  const openCreateSpace = useCallback(() => setCreateSpaceOpen(true), []);
  const { pageKey, prepareNavigation } = usePageRemount();
  const shell = useMemo<ShellContextValue>(
    () => ({ openPalette, openCreateSpace, prepareNavigation }),
    [openPalette, openCreateSpace, prepareNavigation]
  );

  // Astryx's mobile-nav context: SideNavItems in the drawer close it, and the
  // collapse button hides itself on phones.
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
          {!isChatRoute(pathname) && (
            <MobileTopBar
              isNavOpen={drawerOpen}
              drawerId={isMobile ? drawerId : undefined}
              onOpenNav={() => setNavOpen(true)}
            />
          )}
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
          <CreateSpaceDialog isOpen={createSpaceOpen} onOpenChange={setCreateSpaceOpen} />
        </div>
      </AppShellMobileContext>
    </ShellContext>
  );
}
