import { Card } from "@astryxdesign/core/Card";
import { List, ListItem } from "@astryxdesign/core/List";
import { Token } from "@astryxdesign/core/Token";
import type { UseQueryResult } from "@tanstack/react-query";
import { useTranslations } from "use-intl";
import { useId } from "react";
import { QueryStateBoundary } from "@/components/composites/query-state";
import type { Schema } from "@/lib/api/models";
import { cn } from "@/lib/utils";
import { share, type InsightKnowledgeSource } from "./insight-figures";

/** A source's kind, as the space's knowledge tab names it. */
const KIND_LABEL = {
  collection: "space_knowledge_type_collection",
  website: "space_knowledge_type_website",
  integration_knowledge: "space_knowledge_type_integration"
} as const satisfies Record<InsightKnowledgeSource["kind"], string>;

function KindTag({ kind }: { kind: InsightKnowledgeSource["kind"] }) {
  const t = useTranslations();
  return <Token label={t(KIND_LABEL[kind])} size="sm" />;
}

/**
 * A cited source: its name and kind, how many answers cited it, and a bar of
 * that against the most cited source. The count says it in words; the bar
 * only repeats it. A source no longer attached says so.
 */
function CitedSource({ source, most }: { source: InsightKnowledgeSource; most: number }) {
  const t = useTranslations();
  return (
    <ListItem
      align="start"
      label={<span className="block font-medium break-words whitespace-normal">{source.name}</span>}
      description={
        <span className="flex flex-col gap-2">
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <KindTag kind={source.kind} />
            {source.attached ? null : <span>{t("insights_knowledge_detached")}</span>}
          </span>
          <span
            aria-hidden="true"
            className="bg-ax-muted block h-2 w-full overflow-hidden rounded-full"
          >
            <span
              className="bg-ax-accent block h-full rounded-full"
              style={{ width: `${(share(source.answers, most) ?? 0) * 100}%` }}
            />
          </span>
        </span>
      }
      endContent={
        <span className="text-ax-text-secondary text-sm whitespace-nowrap tabular-nums">
          {t("insights_knowledge_answers", { count: source.answers })}
        </span>
      }
    />
  );
}

/**
 * "Kunskapen som används": the knowledge sources the period's answers cited,
 * most cited first, and under them the attached ones no answer cited. Left
 * out for a target without knowledge: once its lists come back empty, and
 * while they load when the summary already says there is none
 * (`hasKnowledge` false). A document's citations go when the document is
 * removed, so a source can look less used than it was; the card says so.
 */
export function KnowledgeUseCard({
  knowledge,
  hasKnowledge,
  className
}: {
  knowledge: UseQueryResult<Schema<"InsightKnowledgeUse">>;
  /** The summary's word on whether the target has knowledge; null before it is in. */
  hasKnowledge: boolean | null;
  className?: string;
}) {
  const t = useTranslations();
  const headingId = useId();
  const unusedId = useId();
  const data = knowledge.data;
  if (data && data.sources.length === 0 && data.unused.length === 0) return null;
  if (!data && knowledge.isPending && hasKnowledge === false) return null;

  return (
    <Card className={cn("min-w-0", className)}>
      <section aria-labelledby={headingId} className="flex flex-col gap-3">
        <h2 id={headingId} className="text-base font-semibold">
          {t("insights_knowledge_heading")}
        </h2>
        <QueryStateBoundary query={knowledge} rows={3}>
          {({ sources, unused }) => {
            const most = sources[0]?.answers ?? 0;
            return (
              <div className="flex flex-col gap-4">
                {sources.length > 0 ? (
                  <List hasDividers edge="bleed" aria-labelledby={headingId}>
                    {sources.map((source) => (
                      <CitedSource
                        key={`${source.kind}:${source.id}`}
                        source={source}
                        most={most}
                      />
                    ))}
                  </List>
                ) : (
                  <p className="text-ax-text-secondary text-sm">
                    {t("insights_knowledge_none_cited")}
                  </p>
                )}
                {unused.length > 0 ? (
                  <div className="border-ax-border flex flex-col gap-2 border-t pt-3">
                    <h3 id={unusedId} className="text-ax-text-secondary text-sm font-normal">
                      {t("insights_knowledge_unused")}
                    </h3>
                    <List density="compact" edge="flush" aria-labelledby={unusedId}>
                      {unused.map((source) => (
                        <ListItem
                          key={`${source.kind}:${source.id}`}
                          label={
                            <span className="block font-medium break-words whitespace-normal">
                              {source.name}
                            </span>
                          }
                          endContent={<KindTag kind={source.kind} />}
                        />
                      ))}
                    </List>
                  </div>
                ) : null}
                <p className="text-ax-text-secondary text-sm">{t("insights_knowledge_limit")}</p>
              </div>
            );
          }}
        </QueryStateBoundary>
      </section>
    </Card>
  );
}
