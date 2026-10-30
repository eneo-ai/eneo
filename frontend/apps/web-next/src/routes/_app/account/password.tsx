import { createFileRoute } from "@tanstack/react-router";
import { ChangePasswordCard } from "@/features/account/change-password";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/account/password")({
  head: routeTitle("change_password"),
  component: () => (
    <div data-pushed-section="">
      <ChangePasswordCard />
    </div>
  )
});
