import { createFileRoute } from "@tanstack/react-router";
import { LoginPage, loginSearch } from "@/features/auth/login-page";
import { routeTitle } from "@/lib/route-head";
import { runtimeConfig } from "@/lib/runtime-config";

export const Route = createFileRoute("/login/")({
  validateSearch: loginSearch,
  head: routeTitle("login"),
  component: function LoginRoute() {
    return (
      <LoginPage
        search={Route.useSearch()}
        accessibilityStatementUrl={runtimeConfig().accessibility_statement_url}
      />
    );
  }
});
