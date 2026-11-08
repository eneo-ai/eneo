import { createFileRoute } from "@tanstack/react-router";
import { DeactivatedPage } from "@/features/auth/deactivated-page";
import { getSessionSnapshot } from "@/lib/api/refusal";
import { routeTitle } from "@/lib/route-head";
import { runtimeConfig } from "@/lib/runtime-config";

export const Route = createFileRoute("/deactivated")({
  // The boot probe has named the restriction before the router exists.
  head: (context) => {
    const session = getSessionSnapshot();
    const inactive = session.status === "deactivated" && session.restriction === 9019;
    return routeTitle(inactive ? "account_inactive" : "organisation_deactivated")(context);
  },
  component: () => (
    <DeactivatedPage accessibilityStatementUrl={runtimeConfig().accessibility_statement_url} />
  )
});
