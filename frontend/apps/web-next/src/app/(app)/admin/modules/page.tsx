import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";
import { unwrap } from "@/lib/api/errors";
import { eneoApi } from "@/lib/api/server";
import { hasPermission } from "@/lib/auth/permissions";
import { pageTitle } from "@/lib/page-metadata";
import { ModulesPage } from "@/features/admin/modules/modules-page";

export const generateMetadata = pageTitle("module_admin_title");

export default async function AdminModulesRoute() {
  const user = await unwrap(eneoApi().GET("/api/v1/users/me/"));
  if (!hasPermission(user)("modules")) redirect("/admin");
  const t = await getTranslations();
  return <ModulesPage title={t("module_admin_title")} />;
}
