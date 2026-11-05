import { createFileRoute } from "@tanstack/react-router";
import { AccountIntegrations } from "@/features/account/account-integrations";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/account/integrations")({
  head: routeTitle("my_integrations"),
  component: AccountIntegrations
});
