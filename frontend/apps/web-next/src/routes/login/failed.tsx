import { createFileRoute } from "@tanstack/react-router";
import { LoginFailedPage, loginSearch } from "@/features/auth/login-page";
import { routeTitle } from "@/lib/route-head";
import { runtimeConfig } from "@/lib/runtime-config";

export const Route = createFileRoute("/login/failed")({
  validateSearch: loginSearch,
  head: routeTitle("login_failed"),
  component: function LoginFailedRoute() {
    return (
      <LoginFailedPage
        search={Route.useSearch()}
        accessibilityStatementUrl={runtimeConfig().accessibility_statement_url}
      />
    );
  }
});
