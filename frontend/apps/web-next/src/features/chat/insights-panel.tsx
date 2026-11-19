import { useState } from "react";
import { AssistantInsights, type InsightsPartner } from "@/features/insights/assistant-insights";
import { defaultInsightFilters, type InsightFilters } from "@/features/insights/insight-figures";
import { useInsightViewUrl } from "@/features/insights/insight-view-url";

/**
 * Insikter on the chat page: the assistant's or group chat's insights view
 * under the chat's header. The filters (the last 30 days and every source to
 * begin with) are the tab's own, not the address's: the chat page rewrites
 * its address from the conversation in Chatt, which goes on behind this tab.
 * A finding opened in place of the overview (`finding`), the feedback
 * inbox's filter (`feedback`) and the analysis open over the view
 * (`analysis`) are in the address; opening a finding, "Läs kommentarerna"
 * and the analysis over the view are history entries of their own, so the
 * browser's Back returns to the overview as it was, and a link or a reload
 * shows them again. The chat page keeps them there while Insikter is shown
 * (`useInsightViewUrl`).
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
  const view = useInsightViewUrl();
  return (
    <AssistantInsights
      partner={partner}
      filters={filters}
      onFiltersChange={setFilters}
      view={view}
      editorHref={editHref}
      hidden={hidden}
    />
  );
}
