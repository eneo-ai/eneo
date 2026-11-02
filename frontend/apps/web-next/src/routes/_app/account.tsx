import { createFileRoute, Outlet } from "@tanstack/react-router";
import { AccountFrame } from "@/features/account/account-frame";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/account")({
  head: routeTitle("my_account"),
  component: () => (
    <AccountFrame>
      <Outlet />
    </AccountFrame>
  )
});
