import { Button } from "@astryxdesign/core/Button";
import { Pencil } from "lucide-react";
import { useSuspenseQuery } from "@tanstack/react-query";
import { useTranslations } from "use-intl";
import { BackLink } from "@/components/composites/back-link";
import { PageHeader } from "@/components/composites/page-header";
import { browserApi } from "@/lib/api/browser";
import { useSpace } from "@/features/spaces/use-space";
import { usePhoneScreen } from "@/lib/hooks/use-media-match";
import { AppRunTabs } from "./app-run-tabs";
import { appQueryOptions } from "./apps";
import { AppSwitcher } from "./app-switcher";

/** App run/results surface, with the active tab tracked in ?tab=. */
export function AppDetail({ appId }: { appId: string }) {
  const t = useTranslations();
  const { routeId } = useSpace();
  const phone = usePhoneScreen();
  const { data: app } = useSuspenseQuery(appQueryOptions(browserApi, appId));

  const base = `/spaces/${routeId}/apps/${appId}`;
  const canEdit = (app.permissions ?? []).includes("edit");

  return (
    <div className="flex w-full max-w-5xl flex-col gap-6">
      <div className="flex flex-col gap-1">
        <BackLink href={`/spaces/${routeId}/apps`} hideOnPhone>
          {t("apps")}
        </BackLink>
        <div className="flex min-w-0 items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2">
            <PageHeader title={app.name} className="min-w-0" />
            <AppSwitcher key={app.id} appId={app.id} />
          </div>
          {canEdit && (
            <Button
              href={`${base}/edit`}
              label={t("edit")}
              tooltip={phone ? t("edit") : undefined}
              isIconOnly={phone}
              icon={phone ? <Pencil aria-hidden="true" /> : undefined}
              variant={phone ? "ghost" : undefined}
            />
          )}
        </div>
      </div>

      <AppRunTabs app={app} base={base} />
    </div>
  );
}
