"use client";

import { SideNavItem } from "@astryxdesign/core/SideNav";
import { Building2, Shield } from "lucide-react";
import { useTranslations } from "next-intl";
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

/** "Organisation" and "Administration" (admins), then the profile button. */
export function NavFooter({ variant }: { variant: NavVariant }) {
  const t = useTranslations();
  const { can } = useAppContext();
  const isAdmin = can("admin");

  return (
    <div className={cn("flex flex-col gap-0.5", NAV_ITEM_CLASSES, SECONDARY_LINK_CLASSES)}>
      {variant === "main" && isAdmin ? (
        <>
          <OrganizationItem />
          <SideNavItem label={t("shell_administration")} icon={Shield} href="/admin" />
        </>
      ) : null}
      <div className="mt-1.5">
        <ProfileMenu />
      </div>
    </div>
  );
}
