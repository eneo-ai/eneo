import { createFileRoute } from "@tanstack/react-router";
import { DeactivatedPage } from "@/features/auth/deactivated-page";
import { routeTitle } from "@/lib/route-head";
import { runtimeConfig } from "@/lib/runtime-config";

export const Route = createFileRoute("/deactivated")({
  head: routeTitle("organisation_deactivated"),
  component: () => (
    <DeactivatedPage accessibilityStatementUrl={runtimeConfig().accessibility_statement_url} />
  )
});
