import { createFileRoute } from "@tanstack/react-router";
import { StorageAdminPage } from "@/features/admin/storage/storage-admin-page";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/admin/storage")({
  head: routeTitle("storage_settings_title"),
  component: StorageAdminPage
});
