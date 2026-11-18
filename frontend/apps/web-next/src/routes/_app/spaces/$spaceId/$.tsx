import { createFileRoute } from "@tanstack/react-router";
import { NotFoundPage } from "@/components/shell/not-found-page";
import { routeTitle } from "@/lib/route-head";

// Unknown space pages still pass through the parent space and permission guards.
export const Route = createFileRoute("/_app/spaces/$spaceId/$")({
  head: routeTitle("page_not_found"),
  component: NotFoundPage
});
