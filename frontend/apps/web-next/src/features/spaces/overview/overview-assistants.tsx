"use client";

import { useCollator } from "@astryxdesign/core/i18n";
import { Bot, Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { EmptyState } from "@/components/composites/empty-state";
import { useAppContext } from "@/components/providers/app-context";
import { CreateChatAppMenu } from "@/features/assistants/create-menu";
import { ChatAppTile } from "@/features/assistants/tile";
import { useSpace } from "../use-space";
import { recentChatItems } from "./overview-data";
import { OverviewLink, OverviewSection } from "./overview-section";

/**
 * Dashed card that starts the existing create flow (blank assistant, template
 * gallery or group chat). The flow's own split button is the control, so the
 * card itself needs no click handling.
 */
function NewAssistantCard() {
  const t = useTranslations();
  const { settings } = useAppContext();

  return (
    <div className="border-ax-border-strong rounded-ax-container flex h-full min-h-40 flex-col items-center justify-center gap-3 border border-dashed p-4 text-center">
      <span
        aria-hidden="true"
        className="bg-ax-muted text-ax-text flex size-9 items-center justify-center rounded-full"
      >
        <Plus className="size-4.5" />
      </span>
      <p className="text-ax-text-secondary text-sm">
        {settings.using_templates
          ? t("space_new_assistant_hint_templates")
          : t("space_new_assistant_hint")}
      </p>
      <CreateChatAppMenu />
    </div>
  );
}

/**
 * The newest assistants and group chats as cards (one row), plus the create
 * card for users who may create. "Visa alla" leads to the assistants tab.
 */
export function OverviewAssistants() {
  const t = useTranslations();
  const { space, routeId, can } = useSpace();
  const collator = useCollator();
  const items = recentChatItems(space, collator.compare);
  const canCreate = can("create", "assistant");
  const shown = items.slice(0, canCreate ? 2 : 3);
  const showStatus = !space.personal;

  return (
    <OverviewSection
      id="overview-assistants"
      title={t("assistants")}
      end={
        items.length > 0 ? (
          <OverviewLink
            href={`/spaces/${routeId}/assistants`}
            label={t("space_view_all_assistants")}
          >
            {t("space_view_all")}
          </OverviewLink>
        ) : null
      }
      className="@container"
    >
      {items.length === 0 ? (
        <EmptyState
          icon={<Bot />}
          title={t("space_assistants_empty_title")}
          description={t("space_assistants_empty_description")}
          headingLevel={3}
          isCompact
          actions={canCreate ? <CreateChatAppMenu /> : undefined}
        />
      ) : (
        <ul className="grid gap-3 @lg:grid-cols-2 @xl:grid-cols-3">
          {shown.map((item) => (
            <li key={item.id} className="min-w-0">
              <ChatAppTile item={item} showStatus={showStatus} showActions={false} />
            </li>
          ))}
          {canCreate ? (
            <li className="min-w-0">
              <NewAssistantCard />
            </li>
          ) : null}
        </ul>
      )}
    </OverviewSection>
  );
}
