import { createFileRoute } from "@tanstack/react-router";
import { LogoutHandoff } from "@/features/auth/logout-handoff";
import { routeTitle } from "@/lib/route-head";
import { runtimeConfig } from "@/lib/runtime-config";

export const Route = createFileRoute("/login/switch-organisation")({
  head: routeTitle("logout"),
  component: () => (
    <LogoutHandoff
      target="/login?tenant="
      switchOrganisation
      accessibilityStatementUrl={runtimeConfig().accessibility_statement_url}
    />
  )
});
