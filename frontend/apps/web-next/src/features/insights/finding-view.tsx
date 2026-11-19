import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { pixel, proportional, type TableColumn } from "@astryxdesign/core/Table";
import { useInfiniteQuery, type UseQueryResult } from "@tanstack/react-query";
import { ArrowLeft, MessageSquareText } from "lucide-react";
import { useFormatter, useTranslations } from "use-intl";
import { useEffect, useId, useRef, type ReactNode, type Ref } from "react";
import { Table } from "@/components/astryx/table";
import { LoadingState } from "@/components/composites/loading-state";
import { LoadMore, QueryStateBoundary } from "@/components/composites/query-state";
import { cursorPagination, flattenPages } from "@/lib/api/pagination";
import type { ChatPartner } from "@/lib/chat/types";
import {
  findingEvidence,
  knowledgeMissReasons,
  share,
  type InsightFilters,
  type InsightFindingCase,
  type InsightSummary,
  type KnowledgeMissReason,
  type OpenableFindingKind
} from "./insight-figures";
import { FINDING_TITLE, type InsightEditorLinks } from "./insight-findings";
import { fetchFindingCases, findingCasesKey } from "./insight-stats";
import { Tile } from "./insight-tile";
import { SourceTag } from "./source-tag";

type CaseRow = InsightFindingCase & { key: string };

/** What each finding counts, as its evidence tiles name it. */
const EVIDENCE_LABEL = {
  knowledge_missed: {
    base: "insights_finding_knowledge_missed_base",
    affected: "insights_finding_knowledge_missed_affected"
  },
  unanswered: {
    base: "insights_finding_unanswered_base",
    affected: "insights_finding_unanswered_affected"
  },
  rephrasing: {
    base: "insights_finding_rephrasing_base",
    affected: "insights_finding_rephrasing_affected"
  }
} as const satisfies Record<OpenableFindingKind, { base: string; affected: string }>;

/** Why the finding is flagged, and that it is an indication. */
const WHY = {
  knowledge_missed: "insights_finding_knowledge_missed_why",
  unanswered: "insights_finding_unanswered_why",
  rephrasing: "insights_finding_rephrasing_why"
} as const satisfies Record<OpenableFindingKind, string>;

/** What to look at next. */
const NEXT = {
  knowledge_missed: "insights_finding_knowledge_missed_next",
  unanswered: "insights_finding_unanswered_next",
  rephrasing: "insights_finding_rephrasing_next"
} as const satisfies Record<OpenableFindingKind, string>;

/** The question the analysis is offered for each finding. */
export const FINDING_SUGGESTION = {
  knowledge_missed: "insights_finding_knowledge_missed_suggestion",
  unanswered: "insights_finding_unanswered_suggestion",
  rephrasing: "insights_finding_rephrasing_suggestion"
} as const satisfies Record<OpenableFindingKind, string>;

/** A knowledge miss's reason in the examples table: never the raw score. */
const REASON = {
  no_results: "insights_finding_reason_no_results",
  uncited: "insights_finding_reason_uncited",
  weak_score: "insights_finding_reason_weak_score"
} as const satisfies Record<KnowledgeMissReason, string>;

/** The misses per reason, under the evidence tile. */
const REASON_COUNT = {
  no_results: "insights_finding_reason_no_results_count",
  uncited: "insights_finding_reason_uncited_count",
  weak_score: "insights_finding_reason_weak_score_count"
} as const satisfies Record<KnowledgeMissReason, string>;

function caseKey(item: InsightFindingCase): string {
  return item.kind === "rephrasing" ? item.session_id : item.question_id;
}

/** An answer's rating in words: "Bra", "Dåligt" or "Inget betyg". */
function RatingCell({ rating }: { rating: -1 | 1 | null }) {
  const t = useTranslations();
  const value = rating === 1 ? "good" : rating === -1 ? "bad" : "none";
  return (
    <span className={rating === null ? "text-ax-text-secondary" : undefined}>
      {t("insights_finding_rating", { rating: value })}
    </span>
  );
}

/**
 * A finding opened ("Visa frågorna"): in place of the overview, under the
 * same filters, with the way back. Its title and the period it covers, the
 * evidence (the cases, what they are a share of, and for knowledge misses
 * their reasons once every case is loaded), why it is flagged, the cases
 * themselves a page at a time with a way into each conversation, and what to
 * do next: the knowledge or the editor where the viewer may edit, and the
 * analysis with a question about the finding ready to send.
 */
export function FindingView({
  partner,
  filters,
  kind,
  summary,
  editor,
  targetKind,
  headingRef,
  onBack,
  onOpenConversation,
  onAskAnalysis
}: {
  partner: Pick<ChatPartner, "type" | "id">;
  filters: InsightFilters;
  kind: OpenableFindingKind;
  summary: UseQueryResult<InsightSummary>;
  editor: InsightEditorLinks | null;
  targetKind: "assistant" | "group_chat";
  /** The title: focus moves to it when the view opens. */
  headingRef: Ref<HTMLHeadingElement>;
  onBack: () => void;
  onOpenConversation: (sessionId: string) => void;
  /** Opens the analysis with the finding's question in its composer, from `trigger`. */
  onAskAnalysis: (trigger: HTMLElement) => void;
}) {
  const t = useTranslations();
  const format = useFormatter();
  const headingId = useId();
  const examplesId = useId();
  const nextId = useId();
  const rowId = useId();
  const tableRef = useRef<HTMLTableElement>(null);

  const cases = useInfiniteQuery({
    ...cursorPagination,
    queryKey: findingCasesKey(partner, filters, kind),
    queryFn: ({ pageParam, signal }) =>
      fetchFindingCases({ partner, filters, kind, cursor: pageParam, signal })
  });
  const pages = cases.data?.pages;
  const rows: CaseRow[] = flattenPages(pages).map((item) => ({ ...item, key: caseKey(item) }));
  const total = pages?.[0]?.total_count ?? null;

  // "Visa fler": once the page it asked for renders, focus the first new row's button.
  const focusPage = useRef<number | null>(null);
  const pageCount = pages?.length ?? 0;
  useEffect(() => {
    const page = focusPage.current;
    if (page === null || pageCount <= page) return;
    focusPage.current = null;
    const first = pages?.slice(0, page).reduce((count, loaded) => count + loaded.items.length, 0);
    tableRef.current
      ?.querySelectorAll("tbody tr")
      [first ?? 0]?.querySelector<HTMLElement>("button")
      ?.focus();
  }, [pageCount, pages]);

  const start = new Date(`${filters.range.start}T00:00:00`);
  const end = new Date(`${filters.range.end}T00:00:00`);
  const scope = t("insights_finding_scope", {
    period: format.dateTimeRange(start, end, { dateStyle: "medium" }),
    source: filters.source ?? "all"
  });

  const questionCell = (id: string, question: string) => (
    <span id={id} className="font-medium break-words whitespace-normal">
      {question}
    </span>
  );
  const readCell = (item: CaseRow, describedBy: string) => (
    <Button
      size="sm"
      variant="secondary"
      label={t("insights_feedback_open")}
      aria-haspopup="dialog"
      aria-describedby={describedBy}
      onClick={() => onOpenConversation(item.session_id)}
    >
      {t("insights_finding_read")}
    </Button>
  );
  const describedBy = (item: CaseRow) => `${rowId}-${item.key}`;

  const columns: TableColumn<CaseRow>[] = [
    kind === "rephrasing"
      ? {
          key: "question",
          header: t("questions"),
          width: proportional(1, { minWidth: 260 }),
          renderCell: (item) =>
            item.kind === "rephrasing" ? (
              <ol id={describedBy(item)} className="flex list-decimal flex-col gap-1 ps-5">
                {item.questions.map((question, index) => (
                  <li key={item.question_ids[index] ?? index} className="break-words">
                    {question}
                  </li>
                ))}
              </ol>
            ) : null
        }
      : {
          key: "question",
          header: t("insights_column_question"),
          width: proportional(1, { minWidth: 240 }),
          renderCell: (item) =>
            item.kind === "rephrasing" ? null : questionCell(describedBy(item), item.question)
        },
    {
      key: "source",
      header: t("insights_source_label"),
      width: pixel(112),
      renderCell: (item) => <SourceTag source={item.source} />
    }
  ];
  if (kind === "knowledge_missed") {
    columns.push({
      key: "reason",
      header: t("insights_tile_knowledge"),
      width: pixel(152),
      renderCell: (item) => (item.kind === "knowledge_missed" ? t(REASON[item.reason]) : null)
    });
  }
  if (kind === "unanswered") {
    columns.push({
      key: "phrase",
      header: t("insights_finding_phrase_column"),
      width: proportional(0.6, { minWidth: 160 }),
      renderCell: (item) =>
        item.kind === "unanswered" ? (
          <span className="break-words whitespace-normal">
            {t("insights_finding_phrase", { phrase: item.phrase })}
          </span>
        ) : null
    });
  }
  if (kind !== "rephrasing") {
    columns.push({
      key: "rating",
      header: t("insights_top_questions_ratings"),
      width: pixel(120),
      renderCell: (item) =>
        item.kind === "rephrasing" ? null : <RatingCell rating={item.rating} />
    });
  }
  columns.push({
    key: "read",
    header: t("insights_finding_conversation_column"),
    width: pixel(136),
    renderCell: (item) => readCell(item, describedBy(item))
  });

  let evidence: ReactNode = null;
  if (summary.data) {
    const counted = findingEvidence(kind, summary.data.period, total);
    const reasons =
      kind === "knowledge_missed"
        ? knowledgeMissReasons(flattenPages(pages), cases.isSuccess && !cases.hasNextPage)
        : null;
    const portion = counted ? share(counted.affected, counted.base) : null;
    evidence = counted ? (
      <dl className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,13rem),1fr))] gap-3">
        <Tile
          label={t(EVIDENCE_LABEL[kind].base)}
          value={{ text: format.number(counted.base) }}
          details={[]}
        />
        <Tile
          label={t(EVIDENCE_LABEL[kind].affected)}
          isIndicative
          value={{ text: format.number(counted.affected) }}
          details={[
            reasons && reasons.length > 0
              ? format.list(
                  reasons.map(({ reason, count }) => t(REASON_COUNT[reason], { count })),
                  { type: "conjunction" }
                )
              : null
          ]}
        />
        <Tile
          label={t("insights_finding_share")}
          isIndicative
          value={
            portion === null
              ? { empty: t("insights_finding_share_none") }
              : { text: format.number(portion, { style: "percent" }) }
          }
          details={[]}
        />
      </dl>
    ) : // Rephrasing counts its cases: they are on their way. Without knowledge
    // there is nothing to count misses of.
    cases.isPending ? (
      <LoadingState rows={1} height={96} />
    ) : null;
  }

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-5">
      <div className="flex flex-col items-start gap-2">
        <Button
          variant="ghost"
          size="sm"
          icon={<ArrowLeft className="size-4" aria-hidden="true" />}
          label={t("insights_finding_back")}
          onClick={onBack}
        />
        <h2
          ref={headingRef}
          id={headingId}
          tabIndex={-1}
          className="text-xl font-semibold focus:outline-none"
        >
          {t(FINDING_TITLE[kind])}
        </h2>
        <p className="text-ax-text-secondary text-sm">{scope}</p>
      </div>

      <section aria-label={t("insights_finding_evidence")}>
        <QueryStateBoundary query={summary} rows={1} height={96}>
          {() => evidence}
        </QueryStateBoundary>
      </section>

      <p className="text-ax-text-secondary max-w-prose">{t(WHY[kind])}</p>

      <Card>
        <section aria-labelledby={examplesId} className="flex flex-col gap-3">
          <h3 id={examplesId} className="text-base font-semibold">
            {t("insights_finding_examples")}
          </h3>
          <QueryStateBoundary query={cases} rows={4} height={56}>
            {() =>
              rows.length === 0 ? (
                <p className="text-ax-text-secondary text-sm">
                  {t("insights_finding_examples_empty")}
                </p>
              ) : (
                <div className="flex flex-col gap-3">
                  <Table
                    ref={tableRef}
                    aria-labelledby={examplesId}
                    data={rows}
                    columns={columns}
                    idKey="key"
                    verticalAlign="top"
                    pinnedColumn="question"
                    className="[--table-sticky-background:var(--color-ax-card)]"
                  />
                  <div className="text-ax-text-secondary flex flex-col items-center gap-2 text-sm">
                    <LoadMore
                      query={cases}
                      label={t("insights_show_more")}
                      onLoad={() => {
                        focusPage.current = pageCount;
                        void cases.fetchNextPage();
                      }}
                    />
                    <span className="tabular-nums">
                      {t("insights_shown_of_total", {
                        shown: rows.length,
                        total: total ?? rows.length
                      })}
                    </span>
                  </div>
                </div>
              )
            }
          </QueryStateBoundary>
        </section>
      </Card>

      <Card>
        <section
          aria-labelledby={nextId}
          className="flex flex-wrap items-center justify-between gap-x-5 gap-y-3"
        >
          <div className="flex min-w-0 flex-[999_1_20rem] flex-col gap-1">
            <h3 id={nextId} className="text-base font-semibold">
              {t("insights_finding_next_heading")}
            </h3>
            <p className="text-ax-text-secondary text-sm">{t(NEXT[kind])}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            {editor && kind !== "rephrasing" ? (
              <Button
                variant="primary"
                label={t("insights_open_knowledge")}
                href={editor.knowledge}
              />
            ) : null}
            {editor && kind !== "knowledge_missed" ? (
              <Button
                variant="secondary"
                label={t("insights_edit_target", { kind: targetKind })}
                href={editor.instructions}
              />
            ) : null}
            <Button
              variant="secondary"
              label={t("insights_finding_ask")}
              icon={<MessageSquareText className="size-4" aria-hidden="true" />}
              onClick={(event) => onAskAnalysis(event.currentTarget)}
            />
          </div>
        </section>
      </Card>
    </section>
  );
}
