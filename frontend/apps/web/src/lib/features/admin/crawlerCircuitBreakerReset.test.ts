import { expect, test } from "vitest";
import { overwriteGetLocale } from "$lib/paraglide/runtime";

import type { CrawlerCircuitBreakerResetCandidate } from "./crawlerCircuitBreakerReset";
import {
  getCrawlerCircuitBreakerResetCopy,
  getCrawlerCircuitBreakerResetWebsiteLabel
} from "./crawlerCircuitBreakerReset";

overwriteGetLocale(() => "en");

const backedOffCandidate: CrawlerCircuitBreakerResetCandidate = {
  website_id: "12345678-1234-4234-8234-123456789abc",
  website_url: "https://example.com",
  website_name: "Example municipality",
  state: "BACKED_OFF",
  update_interval: "daily",
  consecutive_failures: 3,
  next_retry_at: "2026-05-15T10:30:00Z",
  last_crawled_at: "2026-05-14T08:15:00Z",
  updated_at: "2026-05-15T09:00:00Z"
};

const pausedCandidate: CrawlerCircuitBreakerResetCandidate = {
  ...backedOffCandidate,
  website_id: "87654321-1234-4234-8234-123456789abc",
  website_url: "https://paused.example.com",
  website_name: null,
  state: "AUTO_DISABLED",
  update_interval: "never",
  consecutive_failures: 10,
  next_retry_at: null,
  last_crawled_at: null
};

test("backed-off websites get recovery copy and no schedule warning", () => {
  const copy = getCrawlerCircuitBreakerResetCopy(backedOffCandidate);

  expect(copy.dialogTitle).toBe("Resume scheduled crawling?");
  expect(copy.dialogDescription).toBe(
    "This clears the retry backoff for the website below so its scheduled crawl can run again at the next interval. Already indexed content is kept."
  );
  expect(copy.confirmLabel).toBe("Resume crawling");
  expect(copy.followupHint).toBeNull();
  expect(copy.followupTone).toBe("neutral");
  expect(copy.ariaLabel).toContain("Example municipality");
  expect(getCrawlerCircuitBreakerResetWebsiteLabel(backedOffCandidate)).toBe(
    "Example municipality"
  );
});

test("paused-after-failures websites get explicit follow-up about scheduling", () => {
  const copy = getCrawlerCircuitBreakerResetCopy(pausedCandidate);

  expect(copy.dialogTitle).toBe("Clear paused state?");
  expect(copy.dialogDescription).toBe(
    "This clears the paused state for the website below. The crawler stays manual-only until you choose an update interval on the website itself."
  );
  expect(copy.confirmLabel).toBe("Clear paused state");
  expect(copy.followupHint).toBe(
    "Scheduled crawling stays manual-only until you pick an update interval on the website."
  );
  expect(copy.followupTone).toBe("caution");
  expect(getCrawlerCircuitBreakerResetWebsiteLabel(pausedCandidate)).toBe(
    "https://paused.example.com"
  );
});

test("website label falls back to URL when name is missing", () => {
  expect(getCrawlerCircuitBreakerResetWebsiteLabel(pausedCandidate)).toBe(
    "https://paused.example.com"
  );
});

test("website label falls back to truncated id when both name and url are blank", () => {
  expect(
    getCrawlerCircuitBreakerResetWebsiteLabel({
      ...pausedCandidate,
      website_url: "",
      website_name: null
    })
  ).toBe("Website 87654321");
});
