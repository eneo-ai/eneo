import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/_app/spaces/")({
  beforeLoad: () => {
    throw redirect({ to: "/spaces/list", replace: true });
  }
});
