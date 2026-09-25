import {
  Activity,
  Blocks,
  Building2,
  ChartColumn,
  Cpu,
  Database,
  History,
  KeyRound,
  LayoutTemplate,
  Library,
  LifeBuoy,
  Plug,
  Server,
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
  id: "overview" | "governance" | "configuration" | "access";
  labelKey: string;
  items: AdminNavItem[];
};

/**
 * The administration navigation, grouped as in the approved design
 * (Översikt · Styrning · Konfiguration · Användare och åtkomst). Every admin
 * route of the former admin sidebar is here, with the same gating: templates
 * only when the tenant uses templates, modules only with the modules
 * permission. The admin layout still redirects non-admins.
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
        { href: "/admin", icon: Building2, labelKey: "organisation" },
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
        {
          href: "/admin/security-classifications",
          icon: Shield,
          labelKey: "security_classifications"
        },
        { href: "/admin/audit-logs", icon: History, labelKey: "audit_logs" }
      ]
    },
    {
      id: "configuration",
      labelKey: "admin_section_configuration",
      items: [
        { href: "/admin/models", icon: Cpu, labelKey: "models" },
        ...(usingTemplates
          ? [{ href: "/admin/templates", icon: LayoutTemplate, labelKey: "templates" }]
          : []),
        {
          href: "/admin/help-assistants",
          icon: LifeBuoy,
          labelKey: "admin_help_assistants_nav_label"
        },
        { href: "/admin/mcp-servers", icon: Server, labelKey: "mcp_servers" },
        { href: "/admin/tools", icon: Wrench, labelKey: "tools" },
        ...(canManageModules
          ? [{ href: "/admin/modules", icon: Blocks, labelKey: "module_admin_title" }]
          : []),
        { href: "/admin/integrations", icon: Plug, labelKey: "integrations" },
        { href: "/admin/storage", icon: Database, labelKey: "storage_settings_nav" },
        { href: "/admin/skills", icon: SlidersHorizontal, labelKey: "admin_skills_nav_label" }
      ]
    },
    {
      id: "access",
      labelKey: "shell_admin_section_access",
      items: [
        { href: "/admin/users", icon: Users, labelKey: "users" },
        { href: "/admin/roles", icon: UserCheck, labelKey: "roles" },
        { href: "/admin/api-keys", icon: KeyRound, labelKey: "api_keys" }
      ]
    }
  ];
}

/** `/admin` matches only itself; every other item also matches its sub-pages. */
export function isAdminItemActive(pathname: string, href: string): boolean {
  if (href === "/admin") return pathname === "/admin";
  return pathname === href || pathname.startsWith(`${href}/`);
}
