import { useCollator } from "@astryxdesign/core/i18n";
import { Bot } from "lucide-react";
import { useTranslations } from "use-intl";
import { EmptyState } from "@/components/composites/empty-state";
import { AREA_HUES } from "@/components/composites/icon-tile";
import { ResourceCollection } from "@/components/composites/resource-tile";
import { CreateChatAppMenu } from "@/features/assistants/create-menu";
import { ChatAppTile } from "@/features/assistants/tile";
import { useSpace } from "../use-space";
import { recentChatItems } from "./overview-data";
import { OverviewLink, OverviewSection } from "./overview-section";

/**
 * The newest assistants and group chats as cards (three, one row on a tablet),
 * with a small secondary create control in the heading for users who may
 * create: the tab's docked button is the primary action. One control at every
 * width, so a dialog it opened stays open when the screen turns. "Visa alla"
 * leads to the assistants tab.
 */
export function OverviewAssistants() {
  const t = useTranslations();
  const { space, routeId, can } = useSpace();
  const collator = useCollator();
  const items = recentChatItems(space, collator.compare);
  const canCreate = can("create", "assistant");
  const shown = items.slice(0, 3);
  const showStatus = !space.personal;

  return (
    <OverviewSection
      id="overview-assistants"
      title={t("assistants")}
      end={
        items.length > 0 ? (
          <>
            {canCreate ? <CreateChatAppMenu secondary /> : null}
            <OverviewLink
              href={`/spaces/${routeId}/assistants`}
              label={t("space_view_all_assistants")}
            >
              {t("space_view_all")}
            </OverviewLink>
          </>
        ) : null
      }
      className="@container"
    >
      {items.length === 0 ? (
        <EmptyState
          icon={<Bot />}
          hue={AREA_HUES.assistants}
          title={t("space_assistants_empty_title")}
          description={t("space_assistants_empty_description")}
          headingLevel={3}
          isCompact
          actions={canCreate ? <CreateChatAppMenu /> : undefined}
        />
      ) : (
        <ResourceCollection gridClassName="grid gap-3 @lg:grid-cols-2 @xl:grid-cols-3">
          {shown.map((item) => (
            <ChatAppTile key={item.id} item={item} showStatus={showStatus} showActions={false} />
          ))}
        </ResourceCollection>
      )}
    </OverviewSection>
  );
}
