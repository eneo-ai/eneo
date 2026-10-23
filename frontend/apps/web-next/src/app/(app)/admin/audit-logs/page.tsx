import { pageTitle } from "@/lib/page-metadata";
import { AuditPage } from "@/features/admin/audit/audit-page";

export const generateMetadata = pageTitle("audit_logs");

export default function AdminAuditLogsPage() {
  return <AuditPage />;
}
