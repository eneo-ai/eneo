import { Button } from "@astryxdesign/core/Button";
import { useSuspenseQuery } from "@tanstack/react-query";
import { BarChart3, Lock, PowerOff } from "lucide-react";
import { useTranslations } from "use-intl";
import { useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { EmptyState } from "@/components/composites/empty-state";
import { PageHeader } from "@/components/composites/page-header";
import { browserApi } from "@/lib/api/browser";
import { replaceUrl, useSearchParams } from "@/lib/navigation";
import { ViewSearchParams } from "@/lib/view-search-params";
import { assistantQueryOptions } from "@/features/assistants/editor/use-assistant";
import { groupChatQueryOptions } from "@/features/group-chats/use-group-chat";
import { AssistantInsights, type InsightsPartner } from "@/features/insights/assistant-insights";
import { INSIGHT_VIEW_PARAMS, useInsightViewUrl } from "@/features/insights/insight-view-url";
import { insightViewSearch, readInsightViewSearch } from "./assistant-insights-view";

/**
 * The height from the top of `frame` to the end of the page panel (main),
 * less the padding below the frame, so the insights view in it fills the
 * page and scrolls its overview on its own, as it does under the chat's
 * header (the flow page fits its chat below lg the same way). Kept as main
 * resizes (the window, a phone's keyboard). `null` until measured.
 */
function useHeightToPanelEnd(frame: RefObject<HTMLElement | null>): number | null {
  const [height, setHeight] = useState<number | null>(null);
  useLayoutEffect(() => {
    const element = frame.current;
    const main = element?.closest("main");
    if (!element || !main) return;
    const fit = () => {
      const top =
        element.getBoundingClientRect().top - main.getBoundingClientRect().top + main.scrollTop;
      let below = 0;
      for (let node: HTMLElement | null = element.parentElement; node; node = node.parentElement) {
        below += Number.parseFloat(getComputedStyle(node).paddingBottom) || 0;
        if (node === main) break;
      }
      setHeight(Math.max(0, Math.round(main.clientHeight - top - below)));
    };
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(main);
    return () => observer.disconnect();
  }, [frame]);
  return height;
}

/** The rest of the page, for the insights view to fill. */
function FilledFrame({ children }: { children: ReactNode }) {
  const frame = useRef<HTMLDivElement>(null);
  const height = useHeightToPanelEnd(frame);
  return (
    <div
      ref={frame}
      style={height === null ? undefined : { height }}
      className="flex min-h-80 min-w-0 flex-col"
    >
      {children}
    </div>
  );
}

/**
 * An assistant's or group chat's insights in the administration: its name
 * with the way back to the organisation's insights, over the same insights
 * view as the chat page's Insikter tab. The filters, the finding open in
 * place of the overview, the feedback inbox's filter and the analysis open
 * over the view live in the address
 * (`?from=&to=&source=&compare=&finding=&feedback=&analysis=`), so a link or
 * a reload keeps them; an opened finding, "Läs kommentarerna" and the
 * analysis over the view are history entries of their own
 * (`useInsightViewUrl`).
 * The editor's links are there for a caller who may edit the target. A
 * target with insights switched off, or whose insights the caller may not
 * see, says so instead of asking for them.
 */
function TargetInsightsPage({
  partner,
  editorHref,
  offDescription
}: {
  partner: InsightsPartner;
  /** The target's editor, where the caller may edit it; null otherwise. */
  editorHref: string | null;
  /** Where the insights switch is ("Slå på insikter i assistentens inställningar …"). */
  offDescription: string;
}) {
  const t = useTranslations();
  const searchParams = useSearchParams();
  const filters = readInsightViewSearch(searchParams);
  const view = useInsightViewUrl();

  const header = (
    <PageHeader
      title={partner.name}
      actions={
        <Button
          href="/admin/insights"
          label={t("insights")}
          icon={<BarChart3 className="size-4" aria-hidden="true" />}
        />
      }
    />
  );

  // The per-target endpoints refuse both (403): the page says which, without asking.
  const blocked = !partner.insightEnabled
    ? { icon: <PowerOff />, title: t("insights_off_title"), description: offDescription }
    : !partner.permissions?.includes("insight_view")
      ? {
          icon: <Lock />,
          title: t("insights_refused_title"),
          description: t("insights_refused_description")
        }
      : null;
  if (blocked) {
    return (
      <div className="flex w-full min-w-0 flex-col gap-6">
        {header}
        <EmptyState {...blocked} />
      </div>
    );
  }

  return (
    // A change of where the insights view is keeps the analysis mounted: its leave guard does not ask.
    <ViewSearchParams value={INSIGHT_VIEW_PARAMS}>
      <FilledFrame>
        <AssistantInsights
          partner={partner}
          filters={filters}
          onFiltersChange={(next) => replaceUrl(insightViewSearch(next, searchParams.toString()))}
          view={view}
          editorHref={editorHref}
          header={header}
          framed
        />
      </FilledFrame>
    </ViewSearchParams>
  );
}

/** `/admin/insights/assistant/$assistantId`. */
export function AssistantInsightsPage({ assistantId }: { assistantId: string }) {
  const t = useTranslations();
  const { data: assistant } = useSuspenseQuery(assistantQueryOptions(browserApi, assistantId));
  return (
    <TargetInsightsPage
      partner={{
        type: "assistant",
        id: assistant.id,
        name: assistant.name,
        iconId: assistant.icon_id ?? null,
        insightEnabled: assistant.insight_enabled,
        permissions: assistant.permissions
      }}
      editorHref={
        assistant.permissions?.includes("edit")
          ? `/spaces/${assistant.space_id}/assistants/${assistant.id}/edit`
          : null
      }
      offDescription={t("insights_off_description")}
    />
  );
}

/** `/admin/insights/group-chat/$groupChatId`: the same view for a group chat. */
export function GroupChatInsightsPage({ groupChatId }: { groupChatId: string }) {
  const t = useTranslations();
  const { data: groupChat } = useSuspenseQuery(groupChatQueryOptions(browserApi, groupChatId));
  return (
    <TargetInsightsPage
      partner={{
        type: "group-chat",
        id: groupChat.id,
        name: groupChat.name,
        iconId: groupChat.icon_id ?? null,
        insightEnabled: groupChat.insight_enabled,
        permissions: groupChat.permissions
      }}
      editorHref={
        groupChat.permissions?.includes("edit")
          ? `/spaces/${groupChat.space_id}/group-chats/${groupChat.id}/edit`
          : null
      }
      offDescription={t("insights_off_description_group_chat")}
    />
  );
}
