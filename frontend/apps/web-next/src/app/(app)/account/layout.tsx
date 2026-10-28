import { getTranslations } from "next-intl/server";
import { PageHeader } from "@/components/composites/page-header";
import { pageTitle } from "@/lib/page-metadata";
import { AccountNav } from "./account-nav.client";
import { AccountPageBar } from "./account-page-bar.client";

export const generateMetadata = pageTitle("my_account");

/**
 * From 1024 px "Mitt konto" with its tabs heads every account page. Below,
 * where the drawer is, Konto is a page of its own and each page under it a
 * pushed screen with a PageBar back to it (decision 22): the bar sticks to
 * the top of the page panel, outside the page's padding.
 */
export default async function AccountLayout({ children }: { children: React.ReactNode }) {
  const t = await getTranslations();

  return (
    <>
      <AccountPageBar />
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 p-4 sm:p-6">
        <div className="flex flex-col gap-6 max-lg:hidden">
          <PageHeader title={t("my_account")} />
          <AccountNav />
        </div>
        <div className="flex flex-col gap-6">{children}</div>
      </div>
    </>
  );
}
