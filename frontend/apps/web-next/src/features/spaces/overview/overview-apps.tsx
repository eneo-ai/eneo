import { useCollator } from "@astryxdesign/core/i18n";
import { AppWindow } from "lucide-react";
import { useTranslations } from "use-intl";
import { EmptyState } from "@/components/composites/empty-state";
import { AREA_HUES } from "@/components/composites/icon-tile";
import { ResourceCollection } from "@/components/composites/resource-tile";
import { CreateAppButton } from "@/features/apps/create-app";
import { AppTile } from "@/features/apps/tile";
import { useSpace } from "../use-space";
import { recentApps } from "./overview-data";
import { OverviewLink, OverviewSection } from "./overview-section";

/**
 * The newest apps as cards (three, one row on a tablet), with a small
 * secondary create button in the heading for users who may create: the tab's
 * docked button is the primary action. One button at every width, so a dialog
 * it opened stays open when the screen turns. Nothing for someone who has no
 * apps to open and none to create. "Visa alla" leads to the apps tab.
 */
export function OverviewApps() {
  const t = useTranslations();
  const { space, routeId, can } = useSpace();
  const collator = useCollator();
  const items = recentApps(space, collator.compare);
  const canCreate = can("create", "app");
  const shown = items.slice(0, 3);
  const showStatus = !space.personal;
  if (items.length === 0 && !canCreate) return null;

  return (
    <OverviewSection
      id="overview-apps"
      title={t("apps")}
      end={
        items.length > 0 ? (
          <>
            {canCreate ? (
              <span className="phone:hidden contents">
                <CreateAppButton secondary />
              </span>
            ) : null}
            <OverviewLink href={`/spaces/${routeId}/apps`} label={t("space_view_all_apps")}>
              {t("space_view_all")}
            </OverviewLink>
          </>
        ) : null
      }
      className="@container"
    >
      {items.length === 0 ? (
        <EmptyState
          icon={<AppWindow />}
          hue={AREA_HUES.apps}
          title={t("space_apps_empty_title")}
          description={t("space_apps_empty_description")}
          headingLevel={3}
          isCompact
          actions={<CreateAppButton />}
        />
      ) : (
        <ResourceCollection gridClassName="grid gap-3 @lg:grid-cols-2 @xl:grid-cols-3">
          {shown.map((app) => (
            <AppTile key={app.id} app={app} showStatus={showStatus} showActions={false} />
          ))}
        </ResourceCollection>
      )}
    </OverviewSection>
  );
}
