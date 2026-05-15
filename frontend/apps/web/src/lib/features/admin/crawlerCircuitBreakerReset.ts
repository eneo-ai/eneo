import type { components } from "@intric/intric-js";
import { m } from "$lib/paraglide/messages";

export type CrawlerCircuitBreakerResetCandidate =
  components["schemas"]["CrawlerTenantFailureInventoryItem"];

export type CrawlerCircuitBreakerResetTone = "neutral" | "caution" | "destructive";

export interface CrawlerCircuitBreakerResetCopy {
  ariaLabel: string;
  dialogTitle: string;
  dialogDescription: string;
  confirmLabel: string;
  cancelLabel: string;
  busyLabel: string;
  successMessage: string;
  failureMessage: string;
  followupHint: string | null;
  followupTone: CrawlerCircuitBreakerResetTone;
}

function websiteLabel(item: CrawlerCircuitBreakerResetCandidate): string {
  const websiteName = item.website_name?.trim();
  if (websiteName) {
    return websiteName;
  }
  const websiteUrl = item.website_url?.trim();
  if (websiteUrl) {
    return websiteUrl;
  }
  return m.crawler_failure_inventory_unknown_website({
    id: item.website_id.slice(0, 8)
  });
}

export function getCrawlerCircuitBreakerResetCopy(
  item: CrawlerCircuitBreakerResetCandidate
): CrawlerCircuitBreakerResetCopy {
  const website = websiteLabel(item);
  const baseCopy = {
    cancelLabel: m.cancel(),
    busyLabel: m.crawler_circuit_breaker_reset_busy(),
    successMessage: m.crawler_circuit_breaker_reset_success({ website }),
    failureMessage: m.crawler_circuit_breaker_reset_failed()
  };

  if (item.state === "AUTO_DISABLED") {
    return {
      ...baseCopy,
      ariaLabel: m.crawler_circuit_breaker_reset_aria_paused({ website }),
      dialogTitle: m.crawler_circuit_breaker_reset_dialog_title_paused(),
      dialogDescription: m.crawler_circuit_breaker_reset_dialog_description_paused({
        website
      }),
      confirmLabel: m.crawler_circuit_breaker_reset_dialog_confirm_paused(),
      followupHint: m.crawler_circuit_breaker_reset_followup_paused(),
      followupTone: "caution"
    };
  }

  return {
    ...baseCopy,
    ariaLabel: m.crawler_circuit_breaker_reset_aria_backed_off({ website }),
    dialogTitle: m.crawler_circuit_breaker_reset_dialog_title_backed_off(),
    dialogDescription: m.crawler_circuit_breaker_reset_dialog_description_backed_off({
      website
    }),
    confirmLabel: m.crawler_circuit_breaker_reset_dialog_confirm_backed_off(),
    followupHint: null,
    followupTone: "neutral"
  };
}

export function getCrawlerCircuitBreakerResetWebsiteLabel(
  item: CrawlerCircuitBreakerResetCandidate
): string {
  return websiteLabel(item);
}
