"use client";

import { usePathname } from "@/lib/navigation";
import { useTranslations } from "use-intl";
import { adminNavGroups } from "@/components/shell/admin-nav-items";
import { PageBar } from "@/components/shell/page-bar";
import { TOOLS_TAB_HREF } from "@/features/admin/tools/tools-tabs";

/** Admin areas outside the navigation, by the area that lists them. */
const LISTED_UNDER: Record<string, { href: string; labelKey: string }> = {
  "/admin/mcp-servers": { href: TOOLS_TAB_HREF["mcp-servers"], labelKey: "tools" }
};

// Every area, whatever the tenant shows: only the labels are read.
const AREAS = adminNavGroups({
  usingTemplates: true,
  canManageModules: true,
  flowsEnabled: true,
  federationEnabled: true
})
  .flatMap((group) => group.items)
  .filter((item) => item.href !== "/admin");

/**
 * The PageBar of the admin areas: an area goes back to Administration, a page
 * below an area back to that area. The overview (`/admin`) keeps the shell's
 * top bar and its menu.
 */
export function AdminPageBar() {
  const t = useTranslations();
  const pathname = usePathname();
  const [, , area] = pathname.split("/");
  if (!area) return null;

  const areaHref = `/admin/${area}`;
  const item = AREAS.find((candidate) => candidate.href === areaHref);
  if (pathname === areaHref) {
    return (
      <PageBar
        parent={{ label: t("shell_administration"), href: "/admin" }}
        title={item ? t(item.labelKey) : undefined}
      />
    );
  }
  const parent = item ?? LISTED_UNDER[areaHref];
  return (
    <PageBar
      parent={
        parent
          ? { label: t(parent.labelKey), href: parent.href }
          : { label: t("shell_administration"), href: "/admin" }
      }
    />
  );
}
