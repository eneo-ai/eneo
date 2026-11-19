import { Button } from "@astryxdesign/core/Button";
import { ResizeHandle, useResizable } from "@astryxdesign/core/Resizable";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ArrowLeft, Lock, MessagesSquare, MessageSquareText } from "lucide-react";
import { useTranslations } from "use-intl";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { EmptyState } from "@/components/composites/empty-state";
import { PAGE_COLUMN } from "@/components/composites/page-frame";
import type { ChatPartner } from "@/lib/chat/types";
import { useElementWidth } from "@/lib/hooks/use-element-width";
import { cn } from "@/lib/utils";
import { QuestionHistory } from "@/features/admin/insights/question-history";
import { CONVERSATION_MIN_WIDTH, panelFitsBeside } from "@/features/chat/side-panel/side-panel";
import { InsightsAnalysis, type AnalysisSuggestion } from "./chat/insights-analysis";
import { InsightCitationsContext } from "./chat/insight-citations";
import { ExploreConversationsDialog } from "./explore-conversations-dialog";
import { FeedbackInbox } from "./feedback-inbox";
import { FINDING_SUGGESTION, FindingView } from "./finding-view";
import {
  feedbackCounts,
  parseInsightSource,
  type InsightFilters,
  type OpenableFindingKind
} from "./insight-figures";
import {
  findingTrigger,
  insightEditorLinks,
  InsightFindings,
  readCommentsTrigger
} from "./insight-findings";
import {
  insightActivityQueryOptions,
  insightFindingsQueryOptions,
  insightKnowledgeQueryOptions,
  insightSummaryQueryOptions,
  insightToolsQueryOptions,
  insightTopQuestionsQueryOptions,
  isInsightRefusal
} from "./insight-stats";
import type { InsightView } from "./insight-view-url";
import { InsightsOverview } from "./insights-overview";
import { InsightsFilterRow } from "./insights-filter-row";
import { KnowledgeUseCard } from "./knowledge-use";
import { ToolUseCard } from "./tool-use";
import { TopQuestionsCard } from "./top-questions";

/** An assistant or group chat whose insights are shown. */
export type InsightsPartner = ChatPartner & { type: "assistant" | "group-chat" };

const PANEL_WIDTH_STORAGE_KEY = "eneo:insights-analysis-width";
const PANEL_MIN_WIDTH = 360;
/** Astryx's ResizeHandle with a divider takes 1 px of the row. */
const PANEL_HANDLE_WIDTH = 1;

/** The question offered to the analysis for the finding on screen. */
type FindingSuggestion = AnalysisSuggestion & { kind: OpenableFindingKind };

let suggestionCounter = 0;

/**
 * A period without conversations (for the chosen source): one empty state in
 * place of the sections, with what to change, and with the comparison on the
 * previous period's conversations, so a drop to none is not hidden. A
 * finding opened in it keeps its way back.
 */
function NoConversations({
  filters,
  previous,
  onBack
}: {
  filters: InsightFilters;
  /** The previous period's conversations, when compared. */
  previous: number;
  /** The way back from a finding opened here; null on the overview. */
  onBack: (() => void) | null;
}) {
  const t = useTranslations();
  return (
    <div className="flex flex-col items-start gap-3">
      {onBack ? (
        <Button
          variant="ghost"
          size="sm"
          icon={<ArrowLeft className="size-4" aria-hidden="true" />}
          label={t("insights_finding_back")}
          onClick={onBack}
        />
      ) : null}
      <EmptyState
        icon={<MessagesSquare />}
        title={t("insights_empty_title")}
        description={t(filters.source ? "insights_empty_hint_source" : "insights_empty_hint")}
        className="w-full"
      >
        {filters.compare && previous > 0 ? (
          <p className="text-ax-text-secondary text-sm">
            {t("insights_empty_previous", { count: previous })}
          </p>
        ) : null}
      </EmptyState>
    </div>
  );
}

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
 * reads conversations. Under the filters: the period's figures, what to
 * improve ("Det här kan du förbättra"), its activity per day, the commonest
 * questions, the knowledge and the tools the answers used, the conversations
 * themselves behind "Utforska konversationer", the users' ratings
 * ("Återkoppling från användarna") and, for an assistant, the question
 * history with each answer's rating. Each section loads, keeps its figures
 * while the filters change and fails on its own. A period without
 * conversations shows one empty state in their place, under the filters.
 *
 * Where the view is, is the address's (`view`, `useInsightViewUrl`): a
 * finding with examples opens in place of the overview, with the filters
 * above it, and its way back returns focus to the finding's button. Its links
 * to the knowledge and the editor are there only where the viewer may edit
 * the target (`editorHref`). "Läs kommentarerna" filters the feedback inbox
 * to the bad ratings with a comment and moves focus to the inbox; going back
 * from there returns the filter it had and focus to the button.
 *
 * "Fråga analysen" opens the analysis in a side panel (Insiktsanalys): beside
 * the overview where the overview keeps 480 px (decision 14, measured on the
 * view's row, with a handle to resize it as on the flow page), and over the
 * view otherwise. Over the view it is a place of its own in the address
 * (`view.analysis`), so the browser's Back closes it; beside the overview it
 * is the view's layout and Back is not involved. Asked from a finding, it
 * offers the finding's question: in
 * the composer of an analysis not yet started with nothing typed, otherwise
 * as a suggestion in the panel to use. Nothing is sent without a click. The
 * analysis stays mounted when the panel closes, so opening it again shows the
 * same analysis. A conversation an analysis cites or the question history or
 * a rating links to opens read-only in "Utforska konversationer".
 *
 * Where the target's insights are not the caller's to see (403), the view
 * says so instead.
 */
export function AssistantInsights({
  partner,
  filters,
  onFiltersChange,
  view,
  editorHref = null,
  header,
  framed = false,
  hidden = false
}: {
  partner: InsightsPartner;
  filters: InsightFilters;
  onFiltersChange: (filters: InsightFilters) => void;
  /** Where the view is (a finding, the inbox's filter, the analysis over it), kept in the address. */
  view: InsightView;
  /** The target's editor, where the viewer may edit it; null otherwise. */
  editorHref?: string | null;
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
  /** What opened the analysis: focus goes back to it when the panel closes. */
  const opener = useRef<HTMLElement | null>(null);
  const findingHeading = useRef<HTMLHeadingElement>(null);
  const inboxHeading = useRef<HTMLHeadingElement>(null);
  const [explore, setExplore] = useState<{ sessionId: string | null } | null>(null);
  // The analysis is open beside the overview (the view's own layout) or over
  // the view (the address's). It mounts when first opened and then stays, so
  // closing and opening it again shows the same analysis.
  const [openBeside, setOpenBeside] = useState(false);
  const open = openBeside || view.analysis;
  const [analysisMounted, setAnalysisMounted] = useState(open);
  if (open && !analysisMounted) setAnalysisMounted(true);
  const [suggestion, setSuggestion] = useState<FindingSuggestion | null>(null);
  const { finding } = view;
  const { range } = filters;
  // A new source or comparison keeps the figures on screen until the new ones are in.
  const summary = useQuery({
    ...insightSummaryQueryOptions(partner, filters),
    placeholderData: keepPreviousData
  });
  // A period without conversations shows one empty state in place of the
  // sections (the summary on screen decides, so it does not flash between two
  // periods with conversations), and the sections' requests wait.
  const empty = summary.data?.period.conversations.total === 0;
  const section = { placeholderData: keepPreviousData, enabled: !empty };
  const activity = useQuery({ ...insightActivityQueryOptions(partner, filters), ...section });
  const findings = useQuery({ ...insightFindingsQueryOptions(partner, filters), ...section });
  const topQuestions = useQuery({
    ...insightTopQuestionsQueryOptions(partner, filters),
    ...section
  });
  const knowledge = useQuery({ ...insightKnowledgeQueryOptions(partner, filters), ...section });
  const tools = useQuery({ ...insightToolsQueryOptions(partner, filters), ...section });
  const change = (next: Partial<InsightFilters>) => onFiltersChange({ ...filters, ...next });
  const editor = insightEditorLinks(partner.type, editorHref);
  const targetKind = partner.type === "group-chat" ? "group_chat" : "assistant";

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

  // Focus moves into the panel when it opens and back to what opened it
  // ("Fråga analysen") when it closes, Back and Forward included. A panel
  // that comes to cover the view (a narrower window, an address opening it)
  // takes the focus the overview had: the overview is inert under it. Focus
  // stays where it is while the view is not on screen.
  const wasOpen = useRef(open);
  useEffect(() => {
    const was = wasOpen.current;
    wasOpen.current = open;
    if (hidden || was === open) return;
    if (open) aside.current?.focus();
    else (opener.current?.isConnected ? opener.current : trigger.current)?.focus();
  }, [open, hidden]);
  useEffect(() => {
    if (!covered || hidden) return;
    const active = document.activeElement;
    if (active === null || active === document.body || main.current?.contains(active)) {
      aside.current?.focus();
    }
  }, [covered, hidden]);

  // A finding opened here moves focus to its title; its way back returns
  // focus to the finding's button. Back from "Läs kommentarerna" returns
  // focus to that button, Forward to the inbox. What the address shows at
  // load is left where it is, and so is focus while the view is not on screen.
  const isReadingComments = view.isReadingComments;
  const shown = useRef({ finding, isReadingComments });
  useEffect(() => {
    const was = shown.current;
    shown.current = { finding, isReadingComments };
    if (hidden) return;
    if (was.finding !== finding) {
      if (finding) findingHeading.current?.focus();
      else if (was.finding) (findingTrigger(main.current, was.finding) ?? trigger.current)?.focus();
    } else if (was.isReadingComments !== isReadingComments) {
      if (isReadingComments) inboxHeading.current?.focus();
      else (readCommentsTrigger(main.current) ?? trigger.current)?.focus();
    }
  }, [finding, isReadingComments, hidden]);

  /** Opens the analysis: beside the overview where it fits, otherwise over the view as an entry of its own. */
  function openPanel() {
    if (open) aside.current?.focus();
    else if (beside) setOpenBeside(true);
    else view.openAnalysis();
  }

  function closePanel() {
    setOpenBeside(false);
    view.closeAnalysis();
  }

  /** "Fråga analysen": from a finding, with the finding's question offered. */
  function askAnalysis(from: HTMLElement | null) {
    opener.current = from;
    if (finding && suggestion?.kind !== finding) {
      suggestionCounter += 1;
      setSuggestion({ id: suggestionCounter, kind: finding, text: t(FINDING_SUGGESTION[finding]) });
    }
    openPanel();
  }

  function showFinding(next: OpenableFindingKind | null) {
    setSuggestion(null);
    view.onFindingChange(next);
  }

  /** "Läs kommentarerna": the inbox, filtered to the bad ratings with a comment. */
  function readComments() {
    view.readComments();
    inboxHeading.current?.focus();
  }

  const openConversation = (sessionId: string) => setExplore({ sessionId });
  // In a page frame the frame insets the view and holds the pages' shared
  // column. On the chat page the view does both: the chat's inset, and the
  // shared column centred in what the analysis leaves of the row.
  const inset = framed ? "pe-4 pb-2" : "wide:px-6 p-4";
  const column = cn("flex w-full min-w-0 flex-col gap-6", !framed && PAGE_COLUMN);

  if (isInsightRefusal(summary.error)) {
    return (
      <div className={cn("min-h-0 min-w-0 flex-1 overflow-y-auto", inset)}>
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
    <InsightCitationsContext value={openConversation}>
      <div ref={row} className="relative flex min-h-0 min-w-0 flex-1">
        <div
          ref={main}
          inert={covered}
          className={cn("min-h-0 min-w-0 flex-1 overflow-y-auto", inset)}
        >
          <div className={column}>
            {header}
            {/*
              The filters wrap among themselves; "Fråga analysen" keeps the
              top right, at the content's end, whatever the filters do and
              whether the panel is open. It sits level with the period's
              field, under the field's label (Astryx's label line and gap).
              Where the bar is too narrow for both it takes a row of its own
              under the filters, full width as a phone's primary actions are.
            */}
            <section aria-label={t("insights_filters_label")} className="@container">
              <div className="flex flex-col gap-3 @min-[26rem]:flex-row @min-[26rem]:items-start">
                <InsightsFilterRow
                  range={range}
                  onRangeChange={(next) => change({ range: next })}
                  compare={filters.compare}
                  onCompareChange={(compare) => change({ compare })}
                >
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
                </InsightsFilterRow>
                <div className="@min-[26rem]:shrink-0 @min-[26rem]:pt-[calc(var(--text-label-size)*var(--text-label-leading)+var(--spacing-1))]">
                  <Button
                    ref={trigger}
                    label={t("insights_ask_analysis")}
                    variant="primary"
                    icon={<MessageSquareText className="size-4" aria-hidden="true" />}
                    className="w-full @min-[26rem]:w-auto"
                    onClick={(event) => askAnalysis(event.currentTarget)}
                  />
                </div>
              </div>
            </section>
            {empty ? (
              <NoConversations
                filters={filters}
                previous={summary.data?.previous?.conversations.total ?? 0}
                onBack={finding ? () => showFinding(null) : null}
              />
            ) : (
              <>
                <div hidden={finding !== null} className="flex flex-col gap-6">
                  <InsightsOverview
                    summary={summary}
                    activity={activity}
                    filters={filters}
                    findings={
                      <InsightFindings
                        findings={findings}
                        targetKind={targetKind}
                        editor={editor}
                        onOpen={showFinding}
                        onReadComments={readComments}
                      />
                    }
                    details={
                      <>
                        <div className="flex flex-wrap items-start gap-5">
                          <TopQuestionsCard
                            questions={topQuestions}
                            onOpenConversation={openConversation}
                            className="flex-[999_1_560px]"
                          />
                          <KnowledgeUseCard
                            knowledge={knowledge}
                            hasKnowledge={
                              summary.data ? summary.data.period.knowledge !== null : null
                            }
                            className="flex-[1_1_340px]"
                          />
                        </div>
                        <ToolUseCard tools={tools} />
                      </>
                    }
                    onExplore={() => setExplore({ sessionId: null })}
                  />
                  <FeedbackInbox
                    partner={partner}
                    filters={filters}
                    filter={view.feedback}
                    onFilterChange={view.onFeedbackChange}
                    counts={summary.data ? feedbackCounts(summary.data.period) : null}
                    headingRef={inboxHeading}
                    onOpenConversation={openConversation}
                  />
                  {partner.type === "assistant" && (
                    <QuestionHistory
                      assistantId={partner.id}
                      range={range}
                      source={filters.source}
                      onOpenConversation={openConversation}
                    />
                  )}
                </div>
                {finding ? (
                  <FindingView
                    key={finding}
                    partner={partner}
                    filters={filters}
                    kind={finding}
                    summary={summary}
                    editor={editor}
                    targetKind={targetKind}
                    headingRef={findingHeading}
                    onBack={() => showFinding(null)}
                    onOpenConversation={openConversation}
                    onAskAnalysis={askAnalysis}
                  />
                ) : null}
              </>
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
        {analysisMounted && (
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
              // The finding's question, while that finding is on screen.
              suggestion={suggestion && suggestion.kind === finding ? suggestion : null}
              onClose={closePanel}
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
