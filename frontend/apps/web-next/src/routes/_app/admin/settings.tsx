import { createFileRoute } from "@tanstack/react-router";
import { AdminSettingsPage } from "@/features/admin/settings-page";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/admin/settings")({
  head: routeTitle("settings"),
  component: AdminSettingsPage
});
