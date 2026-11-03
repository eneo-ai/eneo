import { createFileRoute } from "@tanstack/react-router";
import { ModuleLoginFailed } from "@/features/auth/module-login-failed";
import { moduleLoginHead } from "@/features/auth/module-login-head";
import { moduleLoginFailureReason } from "@/lib/auth/module-login";
import { runtimeConfig } from "@/lib/runtime-config";

export const Route = createFileRoute("/module-login/failed")({
  validateSearch: (search: Record<string, unknown>) => ({
    reason: moduleLoginFailureReason(search.reason)
  }),
  head: moduleLoginHead("module_login_failed"),
  component: function ModuleLoginFailedRoute() {
    return (
      <ModuleLoginFailed
        reason={Route.useSearch().reason}
        accessibilityStatementUrl={runtimeConfig().accessibility_statement_url}
      />
    );
  }
});
