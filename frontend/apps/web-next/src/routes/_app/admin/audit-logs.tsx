import { createFileRoute } from "@tanstack/react-router";
import { AuditPage } from "@/features/admin/audit/audit-page";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/admin/audit-logs")({
  head: routeTitle("audit_logs"),
  component: AuditPage
});
