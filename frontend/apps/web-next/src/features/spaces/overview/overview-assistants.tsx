import { useCollator } from "@astryxdesign/core/i18n";
import { Bot } from "lucide-react";
import { useTranslations } from "use-intl";
import { EmptyState } from "@/components/composites/empty-state";
import { AREA_HUES } from "@/components/composites/icon-tile";
import { useAppContext } from "@/components/providers/app-context";
import { ResourceCollection } from "@/components/composites/resource-tile";
import { CreateChatAppMenu } from "@/features/assistants/create-menu";
import { ChatAppTile } from "@/features/assistants/tile";
import { usePhoneScreen } from "@/lib/hooks/use-media-match";
import { useSpace } from "../use-space";
import { recentChatItems } from "./overview-data";
import { OverviewCreateCard, OverviewLink, OverviewSection } from "./overview-section";

/**
 * The newest assistants and group chats as cards (one row), plus the create
 * card for users who may create; on a phone the create control sits in the
 * heading instead of a card. Both are small and secondary: the tab's docked
 * button is the primary action. "Visa alla" leads to the assistants tab.
 */
export function OverviewAssistants() {
  const t = useTranslations();
  const { space, routeId, can } = useSpace();
  const collator = useCollator();
  const { settings } = useAppContext();
  const phone = usePhoneScreen();
  const items = recentChatItems(space, collator.compare);
  const canCreate = can("create", "assistant");
  const createCard = canCreate && !phone;
  const shown = items.slice(0, createCard ? 2 : 3);
  const showStatus = !space.personal;

  return (
    <OverviewSection
      id="overview-assistants"
      title={t("assistants")}
      end={
        items.length > 0 ? (
          <>
            {canCreate && phone ? <CreateChatAppMenu secondary /> : null}
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
        <ResourceCollection
          gridClassName="grid gap-3 @lg:grid-cols-2 @xl:grid-cols-3"
          trailing={
            createCard ? (
              <OverviewCreateCard
                hint={
                  settings.using_templates
                    ? t("space_new_assistant_hint_templates")
                    : t("space_new_assistant_hint")
                }
                action={<CreateChatAppMenu secondary />}
              />
            ) : undefined
          }
        >
          {shown.map((item) => (
            <ChatAppTile key={item.id} item={item} showStatus={showStatus} showActions={false} />
          ))}
        </ResourceCollection>
      )}
    </OverviewSection>
  );
}
