import { getTranslations } from "next-intl/server";
import { PageHeader } from "@/components/composites/page-header";
import { pageTitle } from "@/lib/page-metadata";
import { AccountNav } from "./account-nav.client";

export const generateMetadata = pageTitle("my_account");

export default async function AccountLayout({ children }: { children: React.ReactNode }) {
  const t = await getTranslations();

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 p-4 sm:p-6">
      <PageHeader title={t("my_account")} />
      <AccountNav />
      <div className="flex flex-col gap-6">{children}</div>
    </div>
  );
}
