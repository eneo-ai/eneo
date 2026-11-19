import { Card } from "@astryxdesign/core/Card";
import { List, ListItem } from "@astryxdesign/core/List";
import type { UseQueryResult } from "@tanstack/react-query";
import { useTranslations } from "use-intl";
import { useId } from "react";
import { blockingError, ListError, RefreshError } from "@/components/composites/query-state";
import type { Schema } from "@/lib/api/models";
import { getCapability } from "@/features/capabilities/capabilities";
import type { InsightToolUse } from "./insight-figures";

/**
 * A tool's name as the page shows it: a capability by its function's name
 * ("Webbsökning", whichever server serves it), a server's tool by its title
 * or name with the server beside it.
 */
export function useToolLabel(): (tool: InsightToolUse) => { name: string; server: string | null } {
  const t = useTranslations();
  return (tool) => {
    if (tool.kind === "capability") {
      const capability = getCapability(tool.purpose);
      return {
        name: capability ? t(capability.purpose) : (tool.title ?? tool.purpose ?? t("tools")),
        server: null
      };
    }
    return { name: tool.title || tool.tool_name || t("tools"), server: tool.server_name };
  };
}

/**
 * "Verktyg": the tools and functions the period's answers called, most called
 * first, with the calls that failed or were denied where there were any. Only
 * for a target whose answers called a tool: the card is left out otherwise,
 * also while it loads (most targets have none, and a skeleton would come and
 * go). A failure to load says so in the card.
 */
export function ToolUseCard({ tools }: { tools: UseQueryResult<Schema<"InsightToolUsage">> }) {
  const t = useTranslations();
  const headingId = useId();
  const toolLabel = useToolLabel();
  const failed = blockingError(tools);
  const rows = tools.data?.tools ?? [];
  if (!failed && rows.length === 0) return null;

  return (
    <Card>
      <section aria-labelledby={headingId} className="flex flex-col gap-3">
        <h2 id={headingId} className="text-base font-semibold">
          {t("tools")}
        </h2>
        {failed ? (
          <ListError
            error={tools.error}
            isRetrying={tools.isFetching}
            onRetry={() => void tools.refetch()}
          />
        ) : (
          <>
            <RefreshError queries={[tools]} />
            <List hasDividers edge="bleed" aria-labelledby={headingId}>
              {rows.map((tool) => {
                const { name, server } = toolLabel(tool);
                const problems = [
                  tool.failed > 0 ? t("insights_tools_failed", { count: tool.failed }) : null,
                  tool.denied > 0 ? t("insights_tools_denied", { count: tool.denied }) : null
                ].filter((text): text is string => text !== null);
                const description = [server, ...problems].filter(Boolean).join(" · ");
                return (
                  <ListItem
                    key={`${tool.kind}:${tool.purpose ?? ""}:${tool.server_name ?? ""}:${tool.tool_name ?? ""}`}
                    align="start"
                    label={<span className="block break-words whitespace-normal">{name}</span>}
                    description={
                      description ? (
                        <span className="block break-words whitespace-normal">{description}</span>
                      ) : undefined
                    }
                    endContent={
                      <span className="text-ax-text-secondary text-sm whitespace-nowrap tabular-nums">
                        {t("insights_tools_calls", { count: tool.calls })}
                      </span>
                    }
                  />
                );
              })}
            </List>
          </>
        )}
      </section>
    </Card>
  );
}
