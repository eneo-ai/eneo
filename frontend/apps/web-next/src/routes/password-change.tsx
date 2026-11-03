import { createFileRoute } from "@tanstack/react-router";
import { PasswordChangePage } from "@/features/auth/password-change-page";
import { safeNextPath } from "@/lib/auth/safe-next";
import { routeTitle } from "@/lib/route-head";
import { runtimeConfig } from "@/lib/runtime-config";

export const Route = createFileRoute("/password-change")({
  validateSearch: (search: Record<string, unknown>) => ({
    next: typeof search.next === "string" ? safeNextPath(search.next) : undefined
  }),
  head: routeTitle("password_change_required_title"),
  component: function PasswordChangeRoute() {
    return (
      <PasswordChangePage
        next={Route.useSearch().next}
        accessibilityStatementUrl={runtimeConfig().accessibility_statement_url}
      />
    );
  }
});
