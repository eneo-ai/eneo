"use client";

import { SideNavItem, SideNavSection } from "@astryxdesign/core/SideNav";
import { ArrowLeft } from "lucide-react";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { useAppContext } from "@/components/providers/app-context";
import { cn } from "@/lib/utils";
import { adminNavGroups, isAdminItemActive } from "./admin-nav-items";
import { NAV_ITEM_CLASSES } from "./nav-styles";

export function AdminTopContent() {
  const t = useTranslations();
  return (
    // The way back is set apart from the admin pages: secondary, semibold.
    <div className={cn(NAV_ITEM_CLASSES, "[&_a]:text-ax-text-secondary [&_a]:font-semibold")}>
      <SideNavItem label={t("shell_back_to_eneo")} icon={ArrowLeft} size="lg" href="/" />
    </div>
  );
}

export function AdminSections() {
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
