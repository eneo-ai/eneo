"use client";

import { Building2, Cloud, Cpu, History, Key, Plug, ShieldCheck, Users } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";

type NavItem = { href: string; icon: React.ComponentType<{ className?: string }>; label: string };
type NavGroup = { label: string; items: NavItem[] };

function isActive(pathname: string, href: string): boolean {
  if (href === "/admin") return pathname === "/admin";
  return pathname === href || pathname.startsWith(`${href}/`);
}

/**
 * Admin sidebar navigation, grouped like the Svelte AdminMenu. Sections are
 * added as their pages land during the phase-7 migration; legacy roles /
 * user-groups are intentionally dropped (overview OQ-2).
 */
export function AdminNav() {
  const t = useTranslations();
  const pathname = usePathname();

  const groups: NavGroup[] = [
    {
      label: t("admin_section_overview"),
      items: [{ href: "/admin", icon: Building2, label: t("organisation") }]
    },
    {
      label: t("admin_section_governance"),
      items: [
        {
          href: "/admin/security-classifications",
          icon: ShieldCheck,
          label: t("security_classifications")
        }
      ]
    },
    {
      label: t("admin_section_configuration"),
      items: [
        { href: "/admin/models", icon: Cpu, label: t("models") },
        { href: "/admin/mcp-servers", icon: Plug, label: t("mcp_servers") },
        { href: "/admin/integrations", icon: Cloud, label: t("integrations") }
      ]
    },
    {
      label: t("admin_section_analytics_logs"),
      items: [{ href: "/admin/audit-logs", icon: History, label: t("audit_logs") }]
    },
    {
      label: t("admin_section_access"),
      items: [
        { href: "/admin/users", icon: Users, label: t("users") },
        { href: "/admin/api-keys", icon: Key, label: t("api_keys") }
      ]
    }
  ];

  return (
    <nav aria-label={t("admin_nav_aria")} className="flex flex-col gap-4">
      {groups.map((group) => (
        <div key={group.label} className="flex flex-col gap-1">
          <p className="text-muted-foreground px-3 py-1 text-xs font-semibold tracking-wide uppercase">
            {group.label}
          </p>
          {group.items.map((item) => {
            const active = isActive(pathname, item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "text-muted-foreground hover:bg-muted hover:text-foreground flex h-9 items-center gap-2 rounded-lg px-3 text-sm font-medium transition-colors",
                  active && "bg-muted text-foreground"
                )}
              >
                <item.icon className="size-4" />
                {item.label}
              </Link>
            );
          })}
        </div>
      ))}
    </nav>
  );
}
