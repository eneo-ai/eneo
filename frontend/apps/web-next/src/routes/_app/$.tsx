import { createFileRoute } from "@tanstack/react-router";
import { NotFoundPage } from "@/components/shell/not-found-page";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/$")({
  head: routeTitle("page_not_found"),
  component: NotFoundPage
});
