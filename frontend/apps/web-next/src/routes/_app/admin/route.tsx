import { createFileRoute, Outlet } from "@tanstack/react-router";
import { PageFrame } from "@/components/composites/page-frame";
import { AdminPageBar } from "@/features/admin/admin-page-bar";
import { routeTitle } from "@/lib/route-head";
import { requirePermission } from "@/lib/route-helpers";

export const Route = createFileRoute("/_app/admin")({
  beforeLoad: ({ context }) => requirePermission(context, "admin", "/"),
  head: routeTitle("shell_administration"),
  component: AdminLayout
});

function AdminLayout() {
  return (
    <>
      <AdminPageBar />
      <PageFrame>
        <Outlet />
      </PageFrame>
    </>
  );
}
