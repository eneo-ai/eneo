import { createFileRoute, Outlet } from "@tanstack/react-router";
import { SpaceFrame } from "@/features/spaces/frame/space-frame";
import { spaceQueryOptions } from "@/features/spaces/space";
import { SpaceProvider } from "@/features/spaces/use-space";
import { browserApi } from "@/lib/api/browser";
import { readFresh } from "@/lib/api/query";
import { DEFAULT_LANDING } from "@/lib/auth/safe-next";
import { spaceTitle } from "@/lib/route-head";
import { notFoundOn404, requirePermission } from "@/lib/route-helpers";

export const Route = createFileRoute("/_app/spaces/$spaceId")({
  beforeLoad: async ({ context, params }) => {
    if (params.spaceId === "organization")
      await requirePermission(context, "admin", DEFAULT_LANDING);
  },
  loader: ({ context, params }) =>
    notFoundOn404(readFresh(context.queryClient, spaceQueryOptions(browserApi, params.spaceId))),
  head: ({ matches, match }) => spaceTitle(matches, match.context.t),
  component: SpaceLayout
});

function SpaceLayout() {
  const { spaceId } = Route.useParams();
  return (
    <SpaceProvider routeId={spaceId}>
      <SpaceFrame>
        <Outlet />
      </SpaceFrame>
    </SpaceProvider>
  );
}
