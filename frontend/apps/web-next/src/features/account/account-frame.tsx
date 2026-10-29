"use client";

import type { ReactNode } from "react";
import { useTranslations } from "use-intl";
import { PageHeader } from "@/components/composites/page-header";
import { AccountNav } from "./account-nav";
import { AccountPageBar } from "./account-page-bar";

/** Desktop tabs and the mobile back bar share one frame for every account page. */
export function AccountFrame({ children }: { children: ReactNode }) {
  const t = useTranslations();
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
