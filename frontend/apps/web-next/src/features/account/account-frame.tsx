import type { ReactNode } from "react";
import { useTranslations } from "use-intl";
import { PageHeader } from "@/components/composites/page-header";
import { useTouchTablet } from "@/lib/hooks/use-media-match";
import { AccountNav } from "./account-nav";
import { AccountPageBar } from "./account-page-bar";

/**
 * One frame for every account page. Its pages are listed in the sidebar
 * (account-side-nav.tsx), as in the Svelte app; a tablet's SideNav does not
 * hold them, so from 1024 px it has Konto's tabs (#1328); a phone and an iPad
 * held upright have the back bar.
 * The area is "Konto" at every width, as the pushed pages' back links name it.
 */
export function AccountFrame({ children }: { children: ReactNode }) {
  const t = useTranslations();
  const tablet = useTouchTablet();
  return (
    <>
      <AccountPageBar />
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 p-4 sm:p-6">
        <div className="flex flex-col gap-6 max-lg:hidden">
          <PageHeader title={t("account")} />
          {tablet ? <AccountNav /> : null}
        </div>
        <div className="flex flex-col gap-6">{children}</div>
      </div>
    </>
  );
}
