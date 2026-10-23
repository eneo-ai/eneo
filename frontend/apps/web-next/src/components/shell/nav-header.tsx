"use client";

import { Icon } from "@astryxdesign/core/Icon";
import { IconButton } from "@astryxdesign/core/IconButton";
import { useSideNavCollapse } from "@astryxdesign/core/SideNav";
import { PanelLeft } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { EneoIcon, EneoWordMark } from "./eneo-logo";
import { NotificationBells } from "./notification-bells";

/**
 * Wordmark link home, the collapse toggle and the notification bells.
 *
 * One element tree for both states, so the toggle keeps its DOM node, and
 * with it the keyboard focus, when it collapses or expands the nav (WCAG
 * 2.4.3). Expanded, the bells sit before the toggle at the end of the row; in
 * the icon rail the toggle stays right under the logo and the bells follow.
 */
export function NavHeader({ navId }: { navId: string }) {
  const t = useTranslations();
  const { isCollapsed, toggle } = useSideNavCollapse();
  const toggleLabel = isCollapsed ? t("shell_expand_nav") : t("shell_collapse_nav");

  // The SideNav is on the left: the bells' popovers open toward the page.
  const bells = <NotificationBells alignment="start" />;

  return (
    <div
      className={cn("flex items-center", isCollapsed ? "flex-col gap-1" : "min-h-9 gap-0.5 ps-2")}
    >
      <Link
        href="/"
        aria-label={t("shell_home_link")}
        className={cn(
          "focus-visible:outline-ring flex items-center focus-visible:outline-2 focus-visible:outline-offset-2",
          isCollapsed
            ? "rounded-ax-element size-9 justify-center pointer-coarse:size-11"
            : "rounded-ax-inner me-auto h-8 pointer-coarse:h-11"
        )}
      >
        {isCollapsed ? (
          <EneoIcon className="h-6 w-auto" />
        ) : (
          <EneoWordMark className="h-5 w-auto" />
        )}
      </Link>
      {!isCollapsed && bells}
      {/* SideNav's own collapse state, through a plain IconButton rather than
          SideNavCollapseButton: that one has no tooltip, and an icon-only
          control needs its name visible on hover. aria-expanded/-controls
          make it a disclosure for the nav. */}
      <IconButton
        variant="ghost"
        icon={<Icon icon={PanelLeft} />}
        label={toggleLabel}
        tooltip={toggleLabel}
        aria-expanded={!isCollapsed}
        aria-controls={navId}
        onClick={toggle}
      />
      {isCollapsed && bells}
    </div>
  );
}
