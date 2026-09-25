"use client";

import { AppShellMobileContext, useAppShellMobile } from "@astryxdesign/core/AppShell";
import { Button } from "@astryxdesign/core/Button";
import { Icon } from "@astryxdesign/core/Icon";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Kbd } from "@astryxdesign/core/Kbd";
import { SideNavItem, SideNavSection, useSideNavCollapse } from "@astryxdesign/core/SideNav";
import { Skeleton } from "@astryxdesign/core/Skeleton";
import { Bot, LayoutGrid, Plus, Search, SquarePen, User } from "lucide-react";
import { usePathname, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useMemo } from "react";
import { EntityAvatar } from "@/components/composites/entity-avatar";
import { useAppContext } from "@/components/providers/app-context";
import { cn } from "@/lib/utils";
import { useNavSpaces, useRecentConversations } from "./nav-data";
import { NAV_ITEM_CLASSES, SECONDARY_LINK_CLASSES } from "./nav-styles";
import { conversationHref, navTarget, NEW_CONVERSATION_HREF, type NavTarget } from "./routes";
import { useShell } from "./shell-context";

/** Shared spaces shown before "Alla ytor" takes over. */
const MAX_SPACES_IN_NAV = 8;

/** The main-navigation destination the current URL belongs to (for aria-current). */
function useNavTarget(): NavTarget {
  return navTarget(usePathname(), useSearchParams());
}

function NewConversationButton() {
  const t = useTranslations();
  const isCurrent = useNavTarget().kind === "new-conversation";
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
export function MainTopContent() {
  const t = useTranslations();
  const { openPalette } = useShell();
  const mobile = useAppShellMobile();
  const pathname = usePathname();
  // In the drawer, "Sök" opens the palette over the drawer instead of closing
  // it, so focus has somewhere to return to when the palette closes.
  const keepDrawerOpen = useMemo(() => ({ ...mobile, closeMobileNav: () => {} }), [mobile]);

  return (
    // The design sets "Sök" (the only button row) in secondary text.
    <div
      className={cn(
        "flex flex-col gap-1",
        NAV_ITEM_CLASSES,
        "[&_button.astryx-side-nav-item]:text-ax-text-secondary"
      )}
    >
      <NewConversationButton />
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

function SpacesSection() {
  const t = useTranslations();
  const target = useNavTarget();
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

function RecentSection() {
  const t = useTranslations();
  const target = useNavTarget();
  const { isCollapsed } = useSideNavCollapse();
  const { prepareNavigation } = useShell();
  const { conversations } = useRecentConversations();

  // Titles only (no icons): nothing to show in the icon rail.
  if (isCollapsed || conversations.length === 0) return null;

  return (
    <SideNavSection
      title={t("shell_recent")}
      className={cn(NAV_ITEM_CLASSES, SECONDARY_LINK_CLASSES)}
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

export function MainSections() {
  return (
    <div className="flex flex-col gap-3">
      <SpacesSection />
      <RecentSection />
    </div>
  );
}
