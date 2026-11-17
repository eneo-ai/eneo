import { useState } from "react";
import { AssistantInsights, type InsightsPartner } from "@/features/insights/assistant-insights";
import { defaultInsightFilters, type InsightFilters } from "@/features/insights/insight-figures";

/**
 * Insikter on the chat page: the assistant's or group chat's insights view
 * under the chat's header. The filters (the last 30 days and every source to
 * begin with) are the tab's own, not the address's: the chat page rewrites
 * its address from the conversation in Chatt, which goes on behind this tab.
 * `hidden`: the tab is not on screen, so the analysis lays nothing over Chatt.
 */
export function InsightsPanel({
  partner,
  hidden = false
}: {
  partner: InsightsPartner;
  hidden?: boolean;
}) {
  const [filters, setFilters] = useState<InsightFilters>(defaultInsightFilters);
  return (
    <AssistantInsights
      partner={partner}
      filters={filters}
      onFiltersChange={setFilters}
      hidden={hidden}
    />
  );
}
