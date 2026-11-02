import { createFileRoute } from "@tanstack/react-router";
import { AccountHome } from "@/features/account/account-home";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/account/")({
  head: routeTitle("my_account"),
  component: AccountHome
});
