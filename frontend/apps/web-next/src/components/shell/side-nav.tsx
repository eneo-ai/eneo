"use client";

import { AppShellMobileContext, useAppShellMobile } from "@astryxdesign/core/AppShell";
import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Kbd } from "@astryxdesign/core/Kbd";
import { MobileNav } from "@astryxdesign/core/MobileNav";
import {
  SideNav,
  SideNavItem,
  SideNavRenderContext,
  SideNavSection,
  useSideNavCollapse
} from "@astryxdesign/core/SideNav";
import { Skeleton } from "@astryxdesign/core/Skeleton";
import {
  ArrowLeft,
  Bot,
  Building2,
  LayoutGrid,
  PanelLeft,
  Plus,
  Search,
  Shield,
  SquarePen,
  User
} from "lucide-react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Suspense, useMemo } from "react";
import { EntityAvatar } from "@/components/composites/entity-avatar";
import { useAppContext } from "@/components/providers/app-context";
import { cn } from "@/lib/utils";
import { ExpiringKeysNotification } from "@/features/api-keys/expiring-keys-notification";
import { JobIndicator } from "@/features/jobs/job-indicator";
import { adminNavGroups, isAdminItemActive } from "./admin-nav-items";
import { EneoIcon, EneoWordMark } from "./eneo-logo";
import { useNavSpaces, useRecentConversations } from "./nav-data";
import { ProfileMenu } from "./profile-menu";
import { conversationHref, navTarget, NEW_CONVERSATION_HREF, type NavTarget } from "./routes";
import { useShell } from "./shell-context";
import { useSideNavCollapsed } from "./shell-state";

export type NavVariant = "main" | "admin";

/** Shared spaces shown before "Alla ytor" takes over. */
const MAX_SPACES_IN_NAV = 8;

// The design's current-page weight (Astryx selects with 500), and 44 px
// targets on touch layouts (ACCESSIBILITY.md → Target size).
const NAV_ITEM_CLASSES =
  "[&_[aria-current=page]]:font-semibold pointer-coarse:[&_.astryx-side-nav-item]:min-h-11";

type NavTargetChildren = { children: (target: NavTarget) => React.ReactNode };

function PathOnlyTarget({ children }: NavTargetChildren) {
  return children(navTarget(usePathname(), null));
}

function SearchAwareTarget({ children }: NavTargetChildren) {
  return children(navTarget(usePathname(), useSearchParams()));
}

/**
 * The current destination. Reading search params needs a Suspense boundary;
 * until they are known the path alone decides (same items, no conversation
 * selected), so the nav never renders empty.
 */
function WithNavTarget({ children }: NavTargetChildren) {
  return (
    <Suspense fallback={<PathOnlyTarget>{children}</PathOnlyTarget>}>
      <SearchAwareTarget>{children}</SearchAwareTarget>
    </Suspense>
  );
}

/** Wordmark link home, the collapse toggle and the notification bells. */
function NavHeader({ navId }: { navId: string }) {
  const t = useTranslations();
  const { isCollapsed, toggle } = useSideNavCollapse();
  const toggleLabel = isCollapsed ? t("shell_expand_nav") : t("shell_collapse_nav");

  const toggleButton = (
    <IconButton
      variant="ghost"
      icon={<Icon icon={PanelLeft} />}
      label={toggleLabel}
      tooltip={toggleLabel}
      aria-expanded={!isCollapsed}
      aria-controls={navId}
      onClick={toggle}
    />
  );

  // The bells are legacy (Radix) popovers; they sit here on desktop and in
  // the mobile top bar, never inside the modal drawer (see MobileNavDrawer).
  const bells = (
    <>
      <JobIndicator />
      <ExpiringKeysNotification />
    </>
  );

  if (isCollapsed) {
    return (
      <div className="flex flex-col items-center gap-1">
        <Link
          href="/"
          aria-label={t("shell_home_link")}
          className="rounded-ax-element focus-visible:outline-ring flex size-9 items-center justify-center focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          <EneoIcon decorative className="h-6 w-auto" />
        </Link>
        {toggleButton}
        {bells}
      </div>
    );
  }

  return (
    <div className="flex h-9 items-center justify-between gap-1 pl-2">
      <Link
        href="/"
        aria-label={t("shell_home_link")}
        className="rounded-ax-inner focus-visible:outline-ring flex h-8 items-center focus-visible:outline-2 focus-visible:outline-offset-2"
      >
        <EneoWordMark decorative className="h-5 w-auto" />
      </Link>
      <div className="flex items-center gap-0.5">
        {bells}
        {toggleButton}
      </div>
    </div>
  );
}

function NewConversationButton({ isCurrent }: { isCurrent: boolean }) {
  const t = useTranslations();
  const { isCollapsed } = useSideNavCollapse();
  const { closeMobileNav } = useAppShellMobile();
  const { prepareNavigation } = useShell();

  return (
    <Button
      href={NEW_CONVERSATION_HREF}
      label={t("new_conversation")}
      icon={<Icon icon={SquarePen} />}
      isIconOnly={isCollapsed}
      tooltip={isCollapsed ? t("new_conversation") : undefined}
      variant="ghost"
      size="lg"
      elevation="low"
      width={isCollapsed ? undefined : "100%"}
      aria-current={isCurrent ? "page" : undefined}
      onClick={() => {
        prepareNavigation(NEW_CONVERSATION_HREF);
        closeMobileNav();
      }}
      className={cn(
        "bg-ax-surface font-semibold pointer-coarse:min-h-11",
        !isCollapsed && "justify-start px-3"
      )}
    />
  );
}

/** "Ny konversation", "Sök" (⌘K) and "Assistenter": sticky at the top of the main nav. */
function MainTopContent() {
  const t = useTranslations();
  const { openPalette } = useShell();
  const mobile = useAppShellMobile();
  const pathname = usePathname();
  // In the drawer, "Sök" opens the palette over the drawer instead of closing
  // it, so focus has somewhere to return to when the palette closes.
  const keepDrawerOpen = useMemo(() => ({ ...mobile, closeMobileNav: () => {} }), [mobile]);

  return (
    <div className={cn("flex flex-col gap-1", NAV_ITEM_CLASSES)}>
      <WithNavTarget>
        {(target) => <NewConversationButton isCurrent={target.kind === "new-conversation"} />}
      </WithNavTarget>
      <AppShellMobileContext value={keepDrawerOpen}>
        <SideNavItem
          label={t("search")}
          icon={Search}
          size="lg"
          onClick={() => openPalette()}
          aria-keyshortcuts="Meta+K Control+K"
          endContent={
            <span aria-hidden="true" className="flex">
              <Kbd keys="mod+k" />
            </span>
          }
        />
      </AppShellMobileContext>
      <SideNavItem
        label={t("assistants")}
        icon={Bot}
        size="lg"
        href="/dashboard"
        isSelected={pathname === "/dashboard" || pathname.startsWith("/dashboard/")}
      />
    </div>
  );
}

function PersonalTile() {
  return (
    <span
      aria-hidden="true"
      className="bg-ax-muted text-ax-text-secondary rounded-ax-inner inline-flex size-6 shrink-0 items-center justify-center [&_svg]:size-3.5"
    >
      <User />
    </span>
  );
}

function SpacesSection({ target }: { target: NavTarget }) {
  const t = useTranslations();
  const { can } = useAppContext();
  const { openCreateSpace } = useShell();
  const { isCollapsed } = useSideNavCollapse();
  const { spaces, isPending } = useNavSpaces();
  const currentRouteId = target.kind === "space" ? target.routeId : null;

  // Keep the list short; the current space stays visible even past the cap.
  const shown = spaces.slice(0, MAX_SPACES_IN_NAV);
  const current = spaces.find((space) => space.id === currentRouteId);
  if (current && !shown.includes(current)) shown.push(current);

  return (
    <SideNavSection
      title={t("shell_spaces")}
      className={NAV_ITEM_CLASSES}
      endContent={
        !isCollapsed && can("shared_spaces") ? (
          <IconButton
            variant="ghost"
            size="sm"
            icon={<Icon icon={Plus} />}
            label={t("create_space")}
            tooltip={t("create_space")}
            onClick={() => openCreateSpace()}
            className="pointer-coarse:size-11"
          />
        ) : undefined
      }
    >
      <SideNavItem
        label={t("personal")}
        icon={<PersonalTile />}
        href="/spaces/personal/overview"
        isSelected={currentRouteId === "personal"}
      />
      {spaces.length === 0 && isPending && !isCollapsed ? (
        <div aria-hidden="true" className="flex flex-col gap-2 px-2 py-1.5">
          <Skeleton height={16} width="70%" radius={1} />
          <Skeleton height={16} width="55%" radius={1} />
        </div>
      ) : null}
      {shown.map((space) => (
        <SideNavItem
          key={space.id}
          label={space.name}
          icon={<EntityAvatar id={space.id} name={space.name} size="sm" />}
          href={`/spaces/${space.id}/overview`}
          isSelected={space.id === currentRouteId}
        />
      ))}
      <SideNavItem
        label={t("shell_all_spaces")}
        icon={LayoutGrid}
        href="/spaces/list"
        isSelected={target.kind === "all-spaces"}
      />
    </SideNavSection>
  );
}

function RecentSection({ target }: { target: NavTarget }) {
  const t = useTranslations();
  const { isCollapsed } = useSideNavCollapse();
  const { prepareNavigation } = useShell();
  const { conversations } = useRecentConversations();

  // Titles only (no icons): nothing to show in the icon rail.
  if (isCollapsed || conversations.length === 0) return null;

  return (
    <SideNavSection
      title={t("shell_recent")}
      className={cn(NAV_ITEM_CLASSES, "[&_a:not([aria-current=page])]:text-ax-text-secondary")}
    >
      {conversations.map((conversation) => (
        <SideNavItem
          key={conversation.id}
          label={conversation.name.trim() || t("shell_untitled_conversation")}
          href={conversationHref(conversation.id)}
          onClick={() => prepareNavigation(conversationHref(conversation.id))}
          isSelected={target.kind === "conversation" && target.sessionId === conversation.id}
        />
      ))}
    </SideNavSection>
  );
}

function MainSections() {
  return (
    <div className="flex flex-col gap-3">
      <WithNavTarget>
        {(target) => (
          <>
            <SpacesSection target={target} />
            <RecentSection target={target} />
          </>
        )}
      </WithNavTarget>
    </div>
  );
}

function AdminTopContent() {
  const t = useTranslations();
  return (
    <div className={NAV_ITEM_CLASSES}>
      <SideNavItem label={t("shell_back_to_eneo")} icon={ArrowLeft} size="lg" href="/" />
    </div>
  );
}

function AdminSections() {
  const t = useTranslations();
  const pathname = usePathname();
  const { settings, can } = useAppContext();
  const groups = adminNavGroups({
    usingTemplates: Boolean(settings.using_templates),
    canManageModules: can("modules")
  });

  return (
    <div className="flex flex-col gap-2">
      {groups.map((group) => (
        <SideNavSection key={group.id} title={t(group.labelKey)} className={NAV_ITEM_CLASSES}>
          {group.items.map((item) => (
            <SideNavItem
              key={item.href}
              label={t(item.labelKey)}
              icon={item.icon}
              href={item.href}
              isSelected={isAdminItemActive(pathname, item.href)}
            />
          ))}
        </SideNavSection>
      ))}
    </div>
  );
}

/** "Organisation" and "Administration" (admins), then the profile button. */
function NavFooter({ variant }: { variant: NavVariant }) {
  const t = useTranslations();
  const { can } = useAppContext();
  const pathname = usePathname();
  const isAdmin = can("admin");

  return (
    <div
      className={cn(
        "flex flex-col gap-0.5",
        NAV_ITEM_CLASSES,
        "[&_a:not([aria-current=page])]:text-ax-text-secondary"
      )}
    >
      {variant === "main" && isAdmin ? (
        <>
          <SideNavItem
            label={t("organization")}
            icon={Building2}
            href="/spaces/organization/knowledge"
            isSelected={pathname.startsWith("/spaces/organization")}
          />
          <SideNavItem label={t("shell_administration")} icon={Shield} href="/admin" />
        </>
      ) : null}
      <div className="mt-1.5">
        <ProfileMenu />
      </div>
    </div>
  );
}

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
