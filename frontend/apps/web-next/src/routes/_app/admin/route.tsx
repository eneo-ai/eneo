import { createFileRoute, Outlet } from "@tanstack/react-router";
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
      <div className="flex min-w-0 flex-1 flex-col p-4 md:p-6">
        <Outlet />
      </div>
    </>
  );
}
