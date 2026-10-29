import { createFileRoute } from "@tanstack/react-router";
import { InviteNotice } from "@/features/auth/invite-notice";
import { routeTitle } from "@/lib/route-head";
import { runtimeConfig } from "@/lib/runtime-config";

export const Route = createFileRoute("/invite/$")({
  head: routeTitle("invite_title"),
  component: () => (
    <InviteNotice accessibilityStatementUrl={runtimeConfig().accessibility_statement_url} />
  )
});
