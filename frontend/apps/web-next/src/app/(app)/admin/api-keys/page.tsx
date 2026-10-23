import { pageTitle } from "@/lib/page-metadata";
import { OrgApiKeysPage } from "@/features/admin/api-keys/org-api-keys";

export const generateMetadata = pageTitle("api_keys");

export default function AdminApiKeysRoute() {
  return <OrgApiKeysPage />;
}
