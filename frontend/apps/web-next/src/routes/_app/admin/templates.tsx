import { createFileRoute, redirect } from "@tanstack/react-router";
import { TemplatesPage } from "@/features/admin/templates/templates-page";
import {
  appTemplatesQueryOptions,
  assistantTemplatesQueryOptions
} from "@/features/admin/templates/templates";
import { browserApi } from "@/lib/api/browser";
import { readCached, readFresh } from "@/lib/api/query";
import { sessionQueries } from "@/lib/api/session";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/admin/templates")({
  // Only while the organisation uses templates, as in the Svelte admin/templates layout. The
  // redirect is the route's, before anything renders: a page that rendered nothing and then sent
  // the admin on left a headingless, idle panel while the overview loaded.
  beforeLoad: async ({ context: { queryClient } }) => {
    const settings = await readCached(queryClient, sessionQueries(browserApi).settings);
    if (settings.using_templates !== true) throw redirect({ href: "/admin", replace: true });
  },
  loader: async ({ context: { queryClient } }) => {
    await Promise.all([
      readFresh(queryClient, assistantTemplatesQueryOptions(browserApi)),
      readFresh(queryClient, appTemplatesQueryOptions(browserApi))
    ]);
  },
  head: routeTitle("templates"),
  component: TemplatesPage
});
