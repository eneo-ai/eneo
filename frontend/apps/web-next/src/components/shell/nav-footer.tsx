"use client";

import { SideNavItem } from "@astryxdesign/core/SideNav";
import { Building2, Shield } from "lucide-react";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { useAppContext } from "@/components/providers/app-context";
import { cn } from "@/lib/utils";
import { NAV_ITEM_CLASSES, SECONDARY_LINK_CLASSES } from "./nav-styles";
import { ProfileMenu } from "./profile-menu";
import type { NavVariant } from "./routes";

/** "Organisation" and "Administration" (admins), then the profile button. */
export function NavFooter({ variant }: { variant: NavVariant }) {
  const t = useTranslations();
  const { can } = useAppContext();
  const pathname = usePathname();
  const isAdmin = can("admin");

  return (
    <div className={cn("flex flex-col gap-0.5", NAV_ITEM_CLASSES, SECONDARY_LINK_CLASSES)}>
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
