import { useState } from "react";
import { AssistantInsights, type InsightsPartner } from "@/features/insights/assistant-insights";
import {
  defaultInsightFilters,
  type InsightFilters,
  type OpenableFindingKind
} from "@/features/insights/insight-figures";

/**
 * Insikter on the chat page: the assistant's or group chat's insights view
 * under the chat's header. The filters (the last 30 days and every source to
 * begin with) and the finding open in place of the overview are the tab's
 * own, not the address's: the chat page rewrites its address from the
 * conversation in Chatt, which goes on behind this tab. `editHref`: the
 * partner's editor, where the user may edit it. `hidden`: the tab is not on
 * screen, so the analysis lays nothing over Chatt.
 */
export function InsightsPanel({
  partner,
  editHref = null,
  hidden = false
}: {
  partner: InsightsPartner;
  editHref?: string | null;
  hidden?: boolean;
}) {
  const [filters, setFilters] = useState<InsightFilters>(defaultInsightFilters);
  const [finding, setFinding] = useState<OpenableFindingKind | null>(null);
  return (
    <AssistantInsights
      partner={partner}
      filters={filters}
      onFiltersChange={setFilters}
      finding={finding}
      onFindingChange={setFinding}
      editorHref={editHref}
      hidden={hidden}
    />
  );
}
