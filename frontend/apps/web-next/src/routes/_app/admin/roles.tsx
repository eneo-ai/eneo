import { createFileRoute } from "@tanstack/react-router";
import { RolesPage } from "@/features/admin/roles/roles-page";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/admin/roles")({
  head: routeTitle("roles"),
  component: RolesPage
});
