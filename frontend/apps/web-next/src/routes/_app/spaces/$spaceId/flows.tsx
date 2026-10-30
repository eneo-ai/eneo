import { createFileRoute, notFound, Outlet, redirect } from "@tanstack/react-router";
import { flowsAvailable } from "@/features/flows/flows-api";
import { browserApi } from "@/lib/api/browser";
import { readCached } from "@/lib/api/query";
import { sessionQueries } from "@/lib/api/session";

export const Route = createFileRoute("/_app/spaces/$spaceId/flows")({
  beforeLoad: async ({ context, params }) => {
    if (params.spaceId === "organization") {
      throw redirect({ href: "/spaces/organization/knowledge", replace: true });
    }
    const session = sessionQueries(browserApi);
    const [settings, user] = await Promise.all([
      readCached(context.queryClient, session.settings),
      readCached(context.queryClient, session.me)
    ]);
    if (!flowsAvailable(settings, user)) throw notFound();
  },
  component: Outlet
});
