"use client";

import { Icon } from "@astryxdesign/core/Icon";
import { IconButton } from "@astryxdesign/core/IconButton";
import { useSideNavCollapse } from "@astryxdesign/core/SideNav";
import { PanelLeft } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { ExpiringKeysNotification } from "@/features/api-keys/expiring-keys-notification";
import { JobIndicator } from "@/features/jobs/job-indicator";
import { EneoIcon, EneoWordMark } from "./eneo-logo";

/** Wordmark link home, the collapse toggle and the notification bells. */
export function NavHeader({ navId }: { navId: string }) {
  const t = useTranslations();
  const { isCollapsed, toggle } = useSideNavCollapse();
  const toggleLabel = isCollapsed ? t("shell_expand_nav") : t("shell_collapse_nav");

  // SideNav's own collapse state, through a plain IconButton rather than
  // SideNavCollapseButton: that one has no tooltip, and an icon-only control
  // needs its name visible on hover. aria-expanded/-controls make it a
  // disclosure for the nav.
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
  // the mobile top bar, never inside the modal drawer (see MobileTopBar).
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
