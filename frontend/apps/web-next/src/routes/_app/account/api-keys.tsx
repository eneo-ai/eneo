import { createFileRoute } from "@tanstack/react-router";
import { ApiKeys } from "@/features/api-keys/account-api-keys";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/account/api-keys")({
  head: routeTitle("my_api_keys"),
  component: ApiKeys
});
