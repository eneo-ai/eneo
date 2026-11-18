import { createFileRoute } from "@tanstack/react-router";
import { AccountCopyFormat } from "@/features/account/copy-format";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/account/copy-format")({
  head: routeTitle("account_copy_format"),
  component: AccountCopyFormat
});
