import { createFileRoute } from "@tanstack/react-router";
import { AccountAppearance } from "@/features/account/account-appearance";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/account/appearance")({
  head: routeTitle("account_appearance_language"),
  component: AccountAppearance
});
