import { createFileRoute } from "@tanstack/react-router";
import { OrgApiKeysPage } from "@/features/admin/api-keys/org-api-keys";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/admin/api-keys")({
  head: routeTitle("api_keys"),
  component: OrgApiKeysPage
});
