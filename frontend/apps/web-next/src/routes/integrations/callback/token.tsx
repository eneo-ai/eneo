import { createFileRoute } from "@tanstack/react-router";
import { CallbackHandoff } from "@/features/integrations/callback-handoff";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/integrations/callback/token")({
  head: routeTitle("integration_callback_finishing_sign_in"),
  component: CallbackHandoff
});
