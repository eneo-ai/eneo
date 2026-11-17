import { Button } from "@astryxdesign/core/Button";
import { ResizeHandle, useResizable } from "@astryxdesign/core/Resizable";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { Switch } from "@astryxdesign/core/Switch";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Lock, MessageSquareText } from "lucide-react";
import { useTranslations } from "use-intl";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { EmptyState } from "@/components/composites/empty-state";
import type { ChatPartner } from "@/lib/chat/types";
import { useElementWidth } from "@/lib/hooks/use-element-width";
import { cn } from "@/lib/utils";
import { QuestionHistory } from "@/features/admin/insights/question-history";
import { CONVERSATION_MIN_WIDTH, panelFitsBeside } from "@/features/chat/side-panel/side-panel";
import { InsightsAnalysis } from "./chat/insights-analysis";
import { InsightCitationsContext } from "./chat/insight-citations";
import { ExploreConversationsDialog } from "./explore-conversations-dialog";
import { FeedbackInbox } from "./feedback-inbox";
import { parseInsightSource, type InsightFilters } from "./insight-figures";
import {
  insightActivityQueryOptions,
  insightSummaryQueryOptions,
  isInsightRefusal
} from "./insight-stats";
import { InsightsOverview } from "./insights-overview";
import { InsightsRangePicker } from "./insights-range-picker";

/** An assistant or group chat whose insights are shown. */
export type InsightsPartner = ChatPartner & { type: "assistant" | "group-chat" };

const PANEL_WIDTH_STORAGE_KEY = "eneo:insights-analysis-width";
const PANEL_MIN_WIDTH = 360;
/** Astryx's ResizeHandle with a divider takes 1 px of the row. */
const PANEL_HANDLE_WIDTH = 1;

/** The analysis panel's whereabouts: not yet opened (not mounted), open, or closed (kept). */
type PanelState = "unopened" | "open" | "closed";

/**
 * The insights of an assistant or group chat, one view in both places it is
 * shown: the chat page's Insikter tab and the administration's page for an
 * assistant or group chat. It fills the height it is given and scrolls its
 * overview on its own, so the analysis can sit beside it.
 *
 * The filters are the mount's: the period (the last 30 days to begin with),
 * the source (every source, or only users, the widget or API keys) and the
 * comparison with the previous period. The administration keeps them in the
 * address, the chat page in the tab. The source applies to everything that
 * reads conversations. Under the filters: the period's figures, its activity
 * per day, the conversations themselves behind "Utforska konversationer",
 * the users' ratings ("Återkoppling från användarna") and, for an assistant,
 * the question history with each answer's rating.
 *
 * "Fråga analysen" opens the analysis in a side panel (Insiktsanalys): beside
 * the overview where the overview keeps 480 px (decision 14, measured on the
 * view's row, with a handle to resize it as on the flow page), and over the
 * view otherwise. The analysis stays mounted when the panel closes, so
 * opening it again shows the same analysis. A conversation an analysis cites
 * or the question history or a rating links to opens read-only in
 * "Utforska konversationer".
 *
 * Where the target's insights are not the caller's to see (403), the view
 * says so instead.
 */
export function AssistantInsights({
  partner,
  filters,
  onFiltersChange,
  header,
  framed = false,
  hidden = false
}: {
  partner: InsightsPartner;
  filters: InsightFilters;
  onFiltersChange: (filters: InsightFilters) => void;
  /** The page's own header, above the filters (the administration's page header). */
  header?: ReactNode;
  /** The view sits in a page frame that already insets it (PageFrame). */
  framed?: boolean;
  /** The view's page or tab is not on screen: nothing may be laid over the page for it. */
  hidden?: boolean;
}) {
  const t = useTranslations();
  const row = useRef<HTMLDivElement>(null);
  const main = useRef<HTMLDivElement>(null);
  const aside = useRef<HTMLElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const [explore, setExplore] = useState<{ sessionId: string | null } | null>(null);
  const [panel, setPanel] = useState<PanelState>("unopened");
  const open = panel === "open";
  const { range } = filters;
  // A new source or comparison keeps the figures on screen until the new ones are in.
  const summary = useQuery({
    ...insightSummaryQueryOptions(partner, filters),
    placeholderData: keepPreviousData
  });
  const activity = useQuery({
    ...insightActivityQueryOptions(partner, filters),
    placeholderData: keepPreviousData
  });
  const change = (next: Partial<InsightFilters>) => onFiltersChange({ ...filters, ...next });

  // Beside the overview while it keeps its 480 px, measured on the row they
  // share; over the view otherwise. Until the row is measured it is over it.
  const rowWidth = useElementWidth(row);
  const beside = rowWidth !== null && panelFitsBeside(rowWidth);
  const maxWidth =
    rowWidth === null
      ? null
      : Math.max(PANEL_MIN_WIDTH, rowWidth - PANEL_HANDLE_WIDTH - CONVERSATION_MIN_WIDTH);
  const resizable = useResizable({
    containerRef: row,
    defaultSize: "40%",
    minSize: PANEL_MIN_WIDTH,
    maxSize: maxWidth ?? "60%",
    autoSaveId: PANEL_WIDTH_STORAGE_KEY
  });
  const covered = open && !beside;

  // Focus moves into the panel when it opens and back to "Fråga analysen"
  // when it closes. A panel that comes to cover the view (a narrower
  // window) takes the focus the overview had: the overview is inert under it.
  const wasOpen = useRef(false);
  useEffect(() => {
    if (open && !wasOpen.current) aside.current?.focus();
    if (!open && wasOpen.current) trigger.current?.focus();
    wasOpen.current = open;
  }, [open]);
  useEffect(() => {
    if (!covered) return;
    const active = document.activeElement;
    if (active === null || active === document.body || main.current?.contains(active)) {
      aside.current?.focus();
    }
  }, [covered]);

  function openPanel() {
    if (open) aside.current?.focus();
    else setPanel("open");
  }

  const column = cn(
    "flex w-full min-w-0 flex-col gap-6",
    framed ? "pe-4 pb-2" : "wide:px-6 max-w-4xl p-4"
  );

  if (isInsightRefusal(summary.error)) {
    return (
      <div className="min-h-0 min-w-0 flex-1 overflow-y-auto">
        <div className={column}>
          {header}
          <EmptyState
            icon={<Lock />}
            title={t("insights_refused_title")}
            description={t("insights_refused_description")}
          />
        </div>
      </div>
    );
  }

  return (
    <InsightCitationsContext value={(sessionId) => setExplore({ sessionId })}>
      <div ref={row} className="relative flex min-h-0 min-w-0 flex-1">
        <div ref={main} inert={covered} className="min-h-0 min-w-0 flex-1 overflow-y-auto">
          <div className={column}>
            {header}
            <section
              aria-label={t("insights_filters_label")}
              className="flex flex-wrap items-end gap-3"
            >
              <div className="min-w-0 flex-1 basis-56 sm:max-w-80">
                <InsightsRangePicker
                  value={range}
                  onChange={(next) => change({ range: next })}
                  compact
                />
              </div>
              <div className="max-w-full min-w-0">
                <SegmentedControl
                  label={t("insights_source_label")}
                  value={filters.source ?? "all"}
                  onChange={(value) => change({ source: parseInsightSource(value) })}
                >
                  <SegmentedControlItem value="all" label={t("insights_source_all")} />
                  <SegmentedControlItem value="user" label={t("insights_source_filter_user")} />
                  <SegmentedControlItem value="widget" label={t("insights_source_widget")} />
                  <SegmentedControlItem value="api_key" label={t("insights_source_api_key")} />
                </SegmentedControl>
              </div>
              <Switch
                label={t("insights_compare_previous")}
                value={filters.compare}
                onChange={(compare) => change({ compare })}
              />
              <Button
                ref={trigger}
                label={t("insights_ask_analysis")}
                variant="primary"
                icon={<MessageSquareText className="size-4" aria-hidden="true" />}
                onClick={openPanel}
              />
            </section>
            <InsightsOverview
              summary={summary}
              activity={activity}
              filters={filters}
              onExplore={() => setExplore({ sessionId: null })}
            />
            <FeedbackInbox
              partner={partner}
              filters={filters}
              onOpenConversation={(sessionId) => setExplore({ sessionId })}
            />
            {partner.type === "assistant" && (
              <QuestionHistory
                assistantId={partner.id}
                range={range}
                source={filters.source}
                onOpenConversation={(sessionId) => setExplore({ sessionId })}
              />
            )}
          </div>
        </div>
        {open && beside && (
          // The panel sits at the end of the row: dragging the handle left widens it.
          <ResizeHandle
            isReversed
            hasDivider
            label={t("insights_analysis_resize")}
            resizable={resizable.props}
          />
        )}
        {panel !== "unopened" && (
          <aside
            ref={aside}
            aria-label={t("insights_chat_partner_name")}
            tabIndex={-1}
            hidden={!open}
            style={
              beside
                ? { width: maxWidth === null ? resizable.size : Math.min(resizable.size, maxWidth) }
                : undefined
            }
            className={cn(
              "bg-ax-surface flex min-h-0 min-w-0 flex-col focus-visible:outline-none",
              beside ? "relative shrink-0" : "absolute inset-0 z-20"
            )}
          >
            <InsightsAnalysis
              partner={partner}
              range={range}
              hidden={hidden || !open}
              onClose={() => setPanel("closed")}
            />
          </aside>
        )}
      </div>
      {explore && (
        <ExploreConversationsDialog
          key={explore.sessionId ?? "list"}
          partner={partner}
          range={range}
          source={filters.source}
          isOpen
          initialSessionId={explore.sessionId}
          onOpenChange={(isOpen) => {
            if (!isOpen) setExplore(null);
          }}
        />
      )}
    </InsightCitationsContext>
  );
}
