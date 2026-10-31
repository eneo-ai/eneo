"use client";

import { List, ListItem } from "@astryxdesign/core/List";
import { useTranslations } from "use-intl";
import { outputTypeLabel, runtimeInputLabel } from "./flow-labels";
import { FlowStatusBadge } from "./flow-status";
import type { FlowSparse } from "./flows-api";

/**
 * What a flow asks for and what it gives back, in words ("Indata: Ljud ·
 * Resultat: Word-dokument"), from the fields the list already returns. A flow
 * that takes typed text or a form has no upload to name, so only its result
 * is said.
 */
export function flowKindLine(
  flow: Pick<FlowSparse, "input_type" | "output_type">,
  t: (key: string, values?: Record<string, string | number>) => string
): string | null {
  const parts = [
    flow.input_type ? t("flows_row_input", { kind: runtimeInputLabel(flow.input_type, t) }) : null,
    flow.output_type ? t("flows_row_output", { kind: outputTypeLabel(flow.output_type, t) }) : null
  ].filter((part): part is string => part !== null);
  return parts.length > 0 ? parts.join(" · ") : null;
}

/**
 * A space's flows as rows on a phone, where the table's five columns do not
 * fit: the name, what it does, what it takes and gives, and (for those who
 * manage flows) whether it is published. A row opens the flow, where it is run.
 */
export function FlowRows({
  flows,
  base,
  showStatus
}: {
  flows: FlowSparse[];
  base: string;
  showStatus: boolean;
}) {
  const t = useTranslations();
  return (
    <List hasDividers edge="outset" aria-label={t("flows")}>
      {flows.map((flow) => {
        const kind = flowKindLine(flow, t);
        return (
          <ListItem
            key={flow.id}
            href={`${base}/${flow.id}`}
            label={flow.name}
            className="min-h-16"
            description={
              <span className="flex flex-col gap-0.5">
                {flow.description ? (
                  <span className="line-clamp-2 break-words">{flow.description}</span>
                ) : null}
                {kind ? <span>{kind}</span> : null}
                {showStatus ? (
                  <span className="pt-0.5">
                    <FlowStatusBadge publishedVersion={flow.published_version} />
                  </span>
                ) : null}
              </span>
            }
          />
        );
      })}
    </List>
  );
}
