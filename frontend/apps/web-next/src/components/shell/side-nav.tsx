"use client";

import { MobileNav } from "@astryxdesign/core/MobileNav";
import { SideNav, SideNavRenderContext } from "@astryxdesign/core/SideNav";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { AdminSections, AdminTopContent } from "./admin-nav";
import { EneoWordMark } from "./eneo-logo";
import { MainSections, MainTopContent } from "./main-nav";
import { NavFooter } from "./nav-footer";
import { NavHeader } from "./nav-header";
import type { NavVariant } from "./routes";
import { DRAWER_MARKER } from "./shell-context";
import { useSideNavCollapsed } from "./shell-state";

function navLabelKey(variant: NavVariant) {
  return variant === "admin" ? "shell_administration" : "shell_nav_label";
}

/**
 * The desktop SideNav (md and up): a named `nav` landmark that collapses to an
 * icon rail. The collapsed state is a per-browser preference (localStorage).
 */
export function DesktopSideNav({ variant, navId }: { variant: NavVariant; navId: string }) {
  const t = useTranslations();
  const [collapsed, setCollapsed] = useSideNavCollapsed();

  return (
    <SideNav
      id={navId}
      aria-label={t(navLabelKey(variant))}
      collapsible={{ isCollapsed: collapsed, onCollapsedChange: setCollapsed, hasButton: false }}
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
 * Phone layouts: the same navigation in an Astryx MobileNav drawer (a modal
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
        <Link
          href="/"
          aria-label={t("shell_home_link")}
          onClick={() => onOpenChange(false)}
          className="rounded-ax-inner focus-visible:outline-ring ms-2 flex h-11 items-center focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          <EneoWordMark decorative className="h-5 w-auto" />
        </Link>
      }
      className="pointer-coarse:[&_button]:min-h-11 pointer-coarse:[&_button]:min-w-11"
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
