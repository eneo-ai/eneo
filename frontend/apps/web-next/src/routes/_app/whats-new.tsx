import { createFileRoute, redirect } from "@tanstack/react-router";
import { useTranslations } from "use-intl";
import { PageFrame } from "@/components/composites/page-frame";
import { PageBar } from "@/components/shell/page-bar";
import { WhatsNewPage } from "@/features/whats-new/whats-new-page";
import { browserApi } from "@/lib/api/browser";
import { readCached } from "@/lib/api/query";
import { sessionQueries } from "@/lib/api/session";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/whats-new")({
  beforeLoad: async ({ context }) => {
    const settings = await readCached(context.queryClient, sessionQueries(browserApi).settings);
    if (!settings.whats_new_enabled) throw redirect({ to: "/", replace: true });
  },
  head: routeTitle("whats_new"),
  component: WhatsNewRoute
});

function WhatsNewRoute() {
  const t = useTranslations();
  return (
    <>
      <PageBar parent={{ label: t("account"), href: "/account" }} title={t("whats_new")} />
      {/* A reading column, on the pages' shared left edge. */}
      <PageFrame>
        <WhatsNewPage title={t("whats_new")} />
      </PageFrame>
    </>
  );
}
