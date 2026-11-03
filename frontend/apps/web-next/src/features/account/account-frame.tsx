import type { ReactNode } from "react";
import { useTranslations } from "use-intl";
import { PageHeader } from "@/components/composites/page-header";
import { AccountPageBar } from "./account-page-bar";

/**
 * One frame for every account page. Its pages are listed in the sidebar
 * (account-side-nav.tsx), as in the Svelte app; a phone has the back bar.
 * The area is "Konto" at every width, as the pushed pages' back links name it.
 */
export function AccountFrame({ children }: { children: ReactNode }) {
  const t = useTranslations();
  return (
    <>
      <AccountPageBar />
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 p-4 sm:p-6">
        <div className="max-lg:hidden">
          <PageHeader title={t("account")} />
        </div>
        <div className="flex flex-col gap-6">{children}</div>
      </div>
    </>
  );
}
