import { useState } from "react";
import { AssistantInsights, type InsightsPartner } from "@/features/insights/assistant-insights";
import { defaultInsightFilters, type InsightFilters } from "@/features/insights/insight-figures";
import { useInsightFindingUrl } from "@/features/insights/insight-finding-url";

/**
 * Insikter on the chat page: the assistant's or group chat's insights view
 * under the chat's header. The filters (the last 30 days and every source to
 * begin with) are the tab's own, not the address's: the chat page rewrites
 * its address from the conversation in Chatt, which goes on behind this tab.
 * A finding opened in place of the overview is in the address (`finding`)
 * as a history entry of its own, so the browser's Back returns to the
 * overview and a link or a reload opens the finding again; the chat page
 * keeps it there while Insikter is shown (`useInsightFindingUrl`).
 * `editHref`: the partner's editor, where the user may edit it. `hidden`:
 * the tab is not on screen, so the analysis lays nothing over Chatt.
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
  const [finding, onFindingChange] = useInsightFindingUrl();
  return (
    <AssistantInsights
      partner={partner}
      filters={filters}
      onFiltersChange={setFilters}
      finding={finding}
      onFindingChange={onFindingChange}
      editorHref={editHref}
      hidden={hidden}
    />
  );
}
