import { createFileRoute, useLocation } from "@tanstack/react-router";
import { ModuleLoginPage } from "@/features/auth/module-login-page";
import { moduleLoginHead } from "@/features/auth/module-login-head";
import { runtimeConfig } from "@/lib/runtime-config";

export const Route = createFileRoute("/module-login/")({
  head: moduleLoginHead("redirecting"),
  component: function ModuleLoginRoute() {
    return (
      <ModuleLoginPage
        search={useLocation({ select: (location) => location.searchStr })}
        accessibilityStatementUrl={runtimeConfig().accessibility_statement_url}
      />
    );
  }
});
