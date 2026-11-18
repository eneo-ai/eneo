import { createFileRoute } from "@tanstack/react-router";
import { useTranslations } from "use-intl";
import { ModulesPage } from "@/features/admin/modules/modules-page";
import { routeTitle } from "@/lib/route-head";
import { requirePermission } from "@/lib/route-helpers";

export const Route = createFileRoute("/_app/admin/modules")({
  beforeLoad: ({ context }) => requirePermission(context, "modules", "/admin"),
  head: routeTitle("module_admin_title"),
  component: ModulesRoute
});

function ModulesRoute() {
  const t = useTranslations();
  return <ModulesPage title={t("module_admin_title")} />;
}
