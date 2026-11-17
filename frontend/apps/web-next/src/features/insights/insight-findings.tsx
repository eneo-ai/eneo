import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { List, ListItem } from "@astryxdesign/core/List";
import type { UseQueryResult } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "use-intl";
import { useId, type ReactNode } from "react";
import { QueryStateBoundary } from "@/components/composites/query-state";
import type { Schema } from "@/lib/api/models";
import type {
  InsightFinding,
  InsightFindingKind,
  InsightToolUse,
  OpenableFindingKind
} from "./insight-figures";
import { useToolLabel } from "./tool-use";

/**
 * Where the target's settings are, for the viewer who may edit it: the
 * knowledge, the instructions and the tools. Null where the viewer may not.
 */
export type InsightEditorLinks = {
  knowledge: string;
  instructions: string;
  tools: (tool: InsightToolUse) => string;
};

/**
 * The editor's links from its address (`editorHref`, null where the viewer
 * may not edit the target). An assistant's editor opens on the section; a
 * group chat's knowledge and tools are its assistants', so its links open
 * the group chat's editor itself.
 */
export function insightEditorLinks(
  type: "assistant" | "group-chat",
  editorHref: string | null | undefined
): InsightEditorLinks | null {
  if (!editorHref) return null;
  if (type === "group-chat") {
    return { knowledge: editorHref, instructions: editorHref, tools: () => editorHref };
  }
  const section = (id: string) => `${editorHref}?section=${id}#${id}`;
  return {
    knowledge: section("knowledge"),
    instructions: section("instructions"),
    tools: (tool) => section(tool.kind === "capability" ? "capabilities" : "mcp")
  };
}

/** A finding with a view of its own is named by its signal. */
export const FINDING_TITLE = {
  knowledge_missed: "insights_finding_knowledge_missed_title",
  unanswered: "insights_finding_unanswered_title",
  rephrasing: "insights_finding_rephrasing_title"
} as const satisfies Record<OpenableFindingKind, string>;

/** "Visa frågorna": what a finding's view lists. */
const FINDING_OPEN = {
  knowledge_missed: "insights_finding_show_questions",
  unanswered: "insights_finding_show_answers",
  rephrasing: "insights_finding_show_conversations"
} as const satisfies Record<OpenableFindingKind, string>;

/** The button that opened a finding's view, for focus to return to when it closes. */
export function findingTrigger(
  container: HTMLElement | null,
  kind: OpenableFindingKind
): HTMLElement | null {
  return container?.querySelector<HTMLElement>(`[data-finding-trigger="${kind}"]`) ?? null;
}

/** One finding per kind, and one per tool for failing tools. */
function findingKey(finding: InsightFinding): string {
  const tool = finding.tool;
  return tool
    ? `${finding.kind}:${tool.kind}:${tool.purpose ?? ""}:${tool.server_name ?? ""}:${tool.tool_name ?? ""}`
    : finding.kind;
}

function isOpenable(kind: InsightFindingKind): kind is OpenableFindingKind {
  return kind in FINDING_OPEN;
}

/** A finding's title and its evidence line, worded by its signal. */
function useFindingText(): (finding: InsightFinding) => { title: string; evidence: string } {
  const t = useTranslations();
  const format = useFormatter();
  const toolLabel = useToolLabel();
  return (finding) => {
    const { affected, base } = finding;
    switch (finding.kind) {
      case "knowledge_missed":
        return {
          title: t(FINDING_TITLE.knowledge_missed),
          evidence: t("insights_finding_knowledge_missed_evidence", { affected, base })
        };
      case "unanswered":
        return {
          title: t(FINDING_TITLE.unanswered),
          evidence: t("insights_finding_unanswered_evidence", { affected, base })
        };
      case "rephrasing":
        return {
          title: t(FINDING_TITLE.rephrasing),
          evidence: t("insights_finding_rephrasing_evidence", { affected, base })
        };
      case "knowledge_unused": {
        const names = (finding.sources ?? []).map((source) => source.name);
        return {
          title: t("insights_finding_knowledge_unused_title", { count: affected }),
          evidence: t("insights_finding_knowledge_unused_evidence", {
            count: names.length,
            names: format.list(names, { type: "conjunction" })
          })
        };
      }
      case "negative_ratings":
        return {
          title: t("insights_finding_negative_ratings_title"),
          evidence: t("insights_finding_negative_ratings_evidence", { affected, base })
        };
      case "tool_failures":
        return {
          title: t("insights_finding_tool_failures_title", {
            tool: finding.tool ? toolLabel(finding.tool).name : t("tools")
          }),
          evidence: t("insights_finding_tool_failures_evidence", { failed: affected, calls: base })
        };
    }
  };
}

/** A finding's actions: its examples, the setting to change, the ratings to read. */
function FindingActions({
  finding,
  targetKind,
  editor,
  onOpen,
  onReadComments
}: {
  finding: InsightFinding;
  targetKind: "assistant" | "group_chat";
  editor: InsightEditorLinks | null;
  onOpen: (kind: OpenableFindingKind) => void;
  onReadComments: () => void;
}) {
  const t = useTranslations();
  const { kind } = finding;
  const actions: ReactNode[] = [];
  if (isOpenable(kind)) {
    actions.push(
      <Button
        key="open"
        size="sm"
        variant="secondary"
        label={t(FINDING_OPEN[kind])}
        data-finding-trigger={kind}
        onClick={() => onOpen(kind)}
      />
    );
  }
  if (kind === "negative_ratings") {
    actions.push(
      <Button
        key="comments"
        size="sm"
        variant="secondary"
        label={t("insights_finding_read_comments")}
        onClick={onReadComments}
      />
    );
  }
  if (editor && (kind === "knowledge_missed" || kind === "knowledge_unused")) {
    actions.push(
      <Button
        key="knowledge"
        size="sm"
        variant="ghost"
        label={t("insights_open_knowledge")}
        href={editor.knowledge}
      />
    );
  }
  if (editor && kind === "tool_failures" && finding.tool) {
    actions.push(
      <Button
        key="edit"
        size="sm"
        variant="ghost"
        label={t("insights_edit_target", { kind: targetKind })}
        href={editor.tools(finding.tool)}
      />
    );
  }
  if (actions.length === 0) return null;
  return <span className="flex flex-wrap gap-2 pt-1">{actions}</span>;
}

/**
 * "Det här kan du förbättra": what the period's figures point at, most
 * affected first, each worded by its signal with the counts behind it and
 * what to do: open its examples (knowledge misses, answers that cannot
 * answer, rephrased questions), open the knowledge or the editor where the
 * viewer may edit, or read the bad ratings' comments in the feedback inbox.
 * Nothing found is said in one quiet line.
 */
export function InsightFindings({
  findings,
  targetKind,
  editor,
  onOpen,
  onReadComments
}: {
  findings: UseQueryResult<Schema<"InsightFindings">>;
  targetKind: "assistant" | "group_chat";
  editor: InsightEditorLinks | null;
  onOpen: (kind: OpenableFindingKind) => void;
  onReadComments: () => void;
}) {
  const t = useTranslations();
  const headingId = useId();
  const findingText = useFindingText();
  const hasFindings = (findings.data?.findings.length ?? 0) > 0;

  return (
    <Card>
      <section aria-labelledby={headingId} className="flex flex-col gap-3">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <h2 id={headingId} className="text-base font-semibold">
            {t("insights_findings_heading")}
          </h2>
          {hasFindings ? (
            <p className="text-ax-text-secondary text-sm">{t("insights_findings_description")}</p>
          ) : null}
        </div>
        <QueryStateBoundary query={findings} rows={2}>
          {(data) =>
            data.findings.length === 0 ? (
              <p className="text-ax-text-secondary text-sm">{t("insights_findings_empty")}</p>
            ) : (
              <List hasDividers edge="bleed" aria-labelledby={headingId}>
                {data.findings.map((finding) => {
                  const { title, evidence } = findingText(finding);
                  return (
                    <ListItem
                      key={findingKey(finding)}
                      align="start"
                      label={
                        <span className="block font-medium break-words whitespace-normal">
                          {title}
                        </span>
                      }
                      description={
                        <span className="flex flex-col gap-1.5">
                          <span className="break-words whitespace-normal">{evidence}</span>
                          <FindingActions
                            finding={finding}
                            targetKind={targetKind}
                            editor={editor}
                            onOpen={onOpen}
                            onReadComments={onReadComments}
                          />
                        </span>
                      }
                    />
                  );
                })}
              </List>
            )
          }
        </QueryStateBoundary>
      </section>
    </Card>
  );
}
