"use client";

import { SideNavItem } from "@astryxdesign/core/SideNav";
import { Building2, CircleHelp, ExternalLink, Shield } from "lucide-react";
import { useTranslations } from "next-intl";
import type { ComponentProps } from "react";
import { useAppContext } from "@/components/providers/app-context";
import { cn } from "@/lib/utils";
import { useNavTarget } from "./nav-data";
import { NAV_ITEM_CLASSES, SECONDARY_LINK_CLASSES } from "./nav-styles";
import { ProfileMenu } from "./profile-menu";
import type { NavVariant } from "./routes";

function OrganizationItem() {
  const t = useTranslations();
  // Not current while "Senaste" marks the conversation open in its chat.
  const isCurrent = useNavTarget().kind === "organization";
  return (
    <SideNavItem
      label={t("organization")}
      icon={Building2}
      href="/spaces/organization/knowledge"
      isSelected={isCurrent}
    />
  );
}

/** A plain anchor to another site, in a new tab (SideNavItem's own link is next/link). */
function ExternalNavLink({ children, ...props }: ComponentProps<"a">) {
  return (
    <a {...props} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  );
}

/**
 * "Har du en fråga?" → the deployment's help centre (HELP_CENTER_URL, shown
 * when SHOW_HELP_CENTER is on). It opens in a new tab, which the accessible
 * name says, in the rail and the drawer too, where the row's own text is gone.
 */
function HelpCenterItem({ href }: { href: string }) {
  const t = useTranslations();
  return (
    <SideNavItem
      as={ExternalNavLink}
      label={t("have_a_question")}
      aria-label={`${t("have_a_question")} ${t("chat_opens_in_new_tab")}`}
      icon={CircleHelp}
      href={href}
      endContent={<ExternalLink aria-hidden="true" className="size-3.5" />}
    />
  );
}

/** "Organisation" and "Administration" (admins), the help centre, then the profile button. */
export function NavFooter({ variant }: { variant: NavVariant }) {
  const t = useTranslations();
  const { can, links } = useAppContext();
  const isAdmin = can("admin");

  return (
    <div className={cn("flex flex-col gap-0.5", NAV_ITEM_CLASSES, SECONDARY_LINK_CLASSES)}>
      {variant === "main" && isAdmin ? (
        <>
          <OrganizationItem />
          <SideNavItem label={t("shell_administration")} icon={Shield} href="/admin" />
        </>
      ) : null}
      {links.helpCenter ? <HelpCenterItem href={links.helpCenter} /> : null}
      <div className="mt-1.5">
        <ProfileMenu />
      </div>
    </div>
  );
}
