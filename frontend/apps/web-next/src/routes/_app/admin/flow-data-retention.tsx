import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/_app/admin/flow-data-retention")({
  beforeLoad: () => {
    throw redirect({ to: "/admin/flow-settings", replace: true });
  }
});
