import {
  Activity,
  Blocks,
  ChartColumn,
  Cpu,
  Database,
  Globe,
  History,
  KeyRound,
  LayoutDashboard,
  LayoutTemplate,
  Library,
  LifeBuoy,
  Plug,
  Server,
  Settings,
  Shield,
  SlidersHorizontal,
  User,
  UserCheck,
  Users,
  Wrench,
  type LucideIcon
} from "lucide-react";

export type AdminNavItem = {
  href: string;
  icon: LucideIcon;
  /** next-intl key of the label (the page's own title key where it has one). */
  labelKey: string;
};

export type AdminNavGroup = {
  /** Stable id, also the React key. */
  id: "overview" | "governance" | "connections" | "organisation";
  labelKey: string;
  items: AdminNavItem[];
};

/**
 * The administration navigation in four groups (UX review B6):
 * Översikt (what is going on), Styrning (what the organisation allows),
 * Anslutningar (what Eneo talks to) and Organisation (who and what it
 * manages). Every admin route is here, with the same gating as before:
 * templates only when the tenant uses templates, modules only with the
 * modules permission. No group exceeds seven items, so none needs to
 * collapse. The admin layout still redirects non-admins.
 */
export function adminNavGroups({
  usingTemplates,
  canManageModules
}: {
  usingTemplates: boolean;
  canManageModules: boolean;
}): AdminNavGroup[] {
  return [
    {
      id: "overview",
      labelKey: "admin_section_overview",
      items: [
        { href: "/admin", icon: LayoutDashboard, labelKey: "overview" },
        { href: "/admin/insights", icon: ChartColumn, labelKey: "insights" },
        { href: "/admin/usage", icon: Activity, labelKey: "usage" }
      ]
    },
    {
      id: "governance",
      labelKey: "admin_section_governance",
      items: [
        { href: "/admin/personal-assistant", icon: User, labelKey: "governance_title" },
        { href: "/admin/prompt-library", icon: Library, labelKey: "governance_tab_prompts" },
        { href: "/admin/skills", icon: SlidersHorizontal, labelKey: "admin_skills_nav_label" },
        {
          href: "/admin/security-classifications",
          icon: Shield,
          labelKey: "security_classifications"
        },
        { href: "/admin/audit-logs", icon: History, labelKey: "audit_logs" }
      ]
    },
    {
      id: "connections",
      labelKey: "admin_section_connections",
      items: [
        { href: "/admin/models", icon: Cpu, labelKey: "models" },
        { href: "/admin/mcp-servers", icon: Server, labelKey: "mcp_servers" },
        { href: "/admin/integrations", icon: Plug, labelKey: "integrations" },
        ...(canManageModules
          ? [{ href: "/admin/modules", icon: Blocks, labelKey: "module_admin_title" }]
          : []),
        // Capability providers (tool providers), so they stay with the connections.
        { href: "/admin/tools", icon: Wrench, labelKey: "tools" },
        { href: "/admin/api-keys", icon: KeyRound, labelKey: "api_keys" }
      ]
    },
    {
      id: "organisation",
      labelKey: "admin_section_organisation",
      items: [
        { href: "/admin/users", icon: Users, labelKey: "users" },
        { href: "/admin/roles", icon: UserCheck, labelKey: "roles" },
        ...(usingTemplates
          ? [{ href: "/admin/templates", icon: LayoutTemplate, labelKey: "templates" }]
          : []),
        {
          href: "/admin/help-assistants",
          icon: LifeBuoy,
          labelKey: "admin_help_assistants_nav_label"
        },
        { href: "/admin/storage", icon: Database, labelKey: "storage_settings_nav" },
        { href: "/admin/crawler", icon: Globe, labelKey: "admin_crawler_title" },
        { href: "/admin/settings", icon: Settings, labelKey: "settings" }
      ]
    }
  ];
}

/** `/admin` matches only itself; every other item also matches its sub-pages. */
export function isAdminItemActive(pathname: string, href: string): boolean {
  if (href === "/admin") return pathname === "/admin";
  return pathname === href || pathname.startsWith(`${href}/`);
}
