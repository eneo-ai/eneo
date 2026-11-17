import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { pixel, proportional, type TableColumn } from "@astryxdesign/core/Table";
import type { UseQueryResult } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "use-intl";
import { useId } from "react";
import { Table } from "@/components/astryx/table";
import { QueryStateBoundary } from "@/components/composites/query-state";
import type { Schema } from "@/lib/api/models";
import { cn } from "@/lib/utils";
import {
  groupAnsweredShare,
  groupKnowledgeHitShare,
  type InsightQuestionGroup
} from "./insight-figures";

type GroupRow = InsightQuestionGroup & { key: string };

/**
 * "Vanligaste frågorna": the period's commonest questions, grouped by their
 * wording, with how often each was asked, the share of its answers that did
 * not say they cannot answer, its answers' ratings and, for a target with
 * knowledge, the share that found something usable there. Both shares are
 * indicative, and the note under the table says so. A question opens one of
 * its conversations read-only in "Utforska konversationer".
 */
export function TopQuestionsCard({
  questions,
  onOpenConversation,
  className
}: {
  questions: UseQueryResult<Schema<"InsightTopQuestions">>;
  onOpenConversation: (sessionId: string) => void;
  className?: string;
}) {
  const t = useTranslations();
  const format = useFormatter();
  const headingId = useId();
  const percent = (value: number | null) =>
    value === null ? null : format.number(value, { style: "percent" });

  function columns(groups: readonly InsightQuestionGroup[]): TableColumn<GroupRow>[] {
    const shown: TableColumn<GroupRow>[] = [
      {
        key: "question",
        header: t("insights_column_question"),
        width: proportional(1, { minWidth: 220 }),
        renderCell: (group) => (
          <Button
            variant="ghost"
            label={group.question}
            aria-haspopup="dialog"
            className="max-w-full text-left whitespace-normal"
            onClick={() => onOpenConversation(group.sample_session_id)}
          />
        )
      },
      {
        key: "occurrences",
        header: t("insights_top_questions_count"),
        width: pixel(88),
        align: "end",
        renderCell: (group) => (
          <span className="tabular-nums">{format.number(group.occurrences)}</span>
        )
      },
      {
        key: "answered",
        header: t("insights_top_questions_answered"),
        width: pixel(120),
        align: "end",
        renderCell: (group) => (
          <span className="tabular-nums">{percent(groupAnsweredShare(group))}</span>
        )
      },
      {
        key: "ratings",
        header: t("insights_top_questions_ratings"),
        width: pixel(160),
        renderCell: ({ ratings }) =>
          ratings.positive + ratings.negative === 0 ? (
            <span className="text-ax-text-secondary">{t("insights_no_ratings")}</span>
          ) : (
            <span className="tabular-nums">
              {t("insights_top_questions_rating_counts", {
                positive: ratings.positive,
                negative: ratings.negative
              })}
            </span>
          )
      }
    ];
    // Only for a target with knowledge: its answers can have searched it.
    if (groups.some((group) => group.knowledge !== null)) {
      shown.push({
        key: "knowledge",
        header: t("insights_tile_knowledge"),
        width: pixel(160),
        align: "end",
        renderCell: (group) => {
          const hits = percent(groupKnowledgeHitShare(group));
          return hits === null ? (
            <span className="text-ax-text-secondary">
              <span aria-hidden="true">–</span>
              <span className="sr-only">{t("insights_no_knowledge_searches")}</span>
            </span>
          ) : (
            <span className="tabular-nums">{hits}</span>
          );
        }
      });
    }
    return shown;
  }

  return (
    <Card className={cn("min-w-0", className)}>
      <section aria-labelledby={headingId} className="flex flex-col gap-3">
        <h2 id={headingId} className="text-base font-semibold">
          {t("insights_top_questions_heading")}
        </h2>
        <QueryStateBoundary query={questions} rows={4}>
          {({ groups }) =>
            groups.length === 0 ? (
              <p className="text-ax-text-secondary text-sm">{t("insights_top_questions_empty")}</p>
            ) : (
              <>
                <Table
                  aria-labelledby={headingId}
                  data={groups.map((group, index) => ({ ...group, key: `${index}` }))}
                  columns={columns(groups)}
                  idKey="key"
                  verticalAlign="top"
                  pinnedColumn="question"
                  className="[--table-sticky-background:var(--color-ax-card)]"
                />
                <p className="text-ax-text-secondary text-sm">{t("insights_top_questions_note")}</p>
              </>
            )
          }
        </QueryStateBoundary>
      </section>
    </Card>
  );
}
