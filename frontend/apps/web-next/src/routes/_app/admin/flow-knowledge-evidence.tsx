import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/_app/admin/flow-knowledge-evidence")({
  beforeLoad: () => {
    throw redirect({ to: "/admin/flow-settings", hash: "flow-evidence-text", replace: true });
  }
});
