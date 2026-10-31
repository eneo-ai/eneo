import { createFileRoute } from "@tanstack/react-router";
import { AuditPage } from "@/features/admin/audit/audit-page";
import { parseAuditTab } from "@/features/admin/audit/audit-url-filters";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/admin/audit-logs")({
  validateSearch: (search: Record<string, unknown>) => ({
    tab: parseAuditTab(search.tab) === "config" ? ("config" as const) : undefined
  }),
  head: routeTitle("audit_logs"),
  component: AuditPage
});
