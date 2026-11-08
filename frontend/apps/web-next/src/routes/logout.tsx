import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";
import { LogoutHandoff, logoutTarget } from "@/features/auth/logout-handoff";
import { routeTitle } from "@/lib/route-head";
import { runtimeConfig } from "@/lib/runtime-config";

export const Route = createFileRoute("/logout")({
  validateSearch: z.object({ reason: z.string().optional(), next: z.string().optional() }),
  head: routeTitle("logout"),
  component: function LogoutRoute() {
    return (
      <LogoutHandoff
        target={logoutTarget(Route.useSearch())}
        accessibilityStatementUrl={runtimeConfig().accessibility_statement_url}
      />
    );
  }
});
