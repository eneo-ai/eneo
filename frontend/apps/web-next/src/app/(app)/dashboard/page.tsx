import { getTranslations } from "next-intl/server";
import { UsersMeSmoke } from "./users-me-smoke";

export default async function DashboardPage() {
  const t = await getTranslations();

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold">{t("dashboard")}</h1>
      <UsersMeSmoke />
    </div>
  );
}
