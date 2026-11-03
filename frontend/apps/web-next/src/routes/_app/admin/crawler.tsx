import { createFileRoute } from "@tanstack/react-router";
import { CrawlerPage } from "@/features/admin/crawler/crawler-page";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/admin/crawler")({
  head: routeTitle("admin_crawler_title"),
  component: CrawlerPage
});
