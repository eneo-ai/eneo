import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/_app/admin/flow-input-limits")({
  beforeLoad: () => {
    throw redirect({ to: "/admin/flow-settings", hash: "flow-files", replace: true });
  }
});
