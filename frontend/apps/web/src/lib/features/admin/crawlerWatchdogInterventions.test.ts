import { expect, test } from "vitest";
import { overwriteGetLocale } from "$lib/paraglide/runtime";

import type { CrawlerWatchdogInterventionItem } from "./crawlerWatchdogInterventions";
import {
  getCrawlerWatchdogInterventionOutcomeLabel,
  getCrawlerWatchdogInterventionResultLabels,
  getCrawlerWatchdogInterventionWebsiteLabel
} from "./crawlerWatchdogInterventions";

overwriteGetLocale(() => "en");

const baseIntervention: CrawlerWatchdogInterventionItem = {
  crawl_run_id: "22222222-2222-4222-8222-222222222222",
  job_id: "11111111-1111-4111-8111-111111111111",
  website_id: "12345678-1234-4234-8234-123456789abc",
  website_name: null,
  tenant_id: "33333333-3333-4333-8333-333333333333",
  tenant_display_name: "Tenant",
  outcome_code: "CRAWL_RUNTIME_TIMEOUT",
  failure_summary: { DOWNLOAD_ERROR: 2 },
  finished_at: "2026-05-12T14:14:50.000Z",
  pages_crawled: 300,
  files_downloaded: 1,
  pages_failed: 2,
  files_failed: 0,
  pages_source_retained: 0,
  pages_hash_retained: 290,
  files_hash_retained: 1,
  files_too_large_skipped: 12,
  embedding_model_name_snapshot: null,
  embedding_model_litellm_name_snapshot: null,
  embedding_model_provider_snapshot: null,
  embedding_input_tokens: null,
  embedding_total_cost_usd: null,
  embedding_usage_source: null
};

test("watchdog intervention labels use typed outcome text and stable website fallback", () => {
  expect(getCrawlerWatchdogInterventionOutcomeLabel(baseIntervention)).toBe(
    "The crawl ran too long and was stopped"
  );
  expect(getCrawlerWatchdogInterventionWebsiteLabel(baseIntervention)).toBe("Website 12345678");
});

test("watchdog intervention result labels distinguish work, retained content, size skips, and failures", () => {
  expect(
    getCrawlerWatchdogInterventionResultLabels(baseIntervention).map((label) => label.label)
  ).toEqual([
    "Fetched 300 pages and 1 file",
    "Indexed 8 pages",
    "Unchanged: 290 pages and 1 file",
    "Too large: 12 files",
    "Failed: 2 pages"
  ]);
});

test("watchdog intervention labels prefer stored website names", () => {
  expect(
    getCrawlerWatchdogInterventionWebsiteLabel({
      ...baseIntervention,
      website_name: "Hudiksvall preschool"
    })
  ).toBe("Hudiksvall preschool");
});
