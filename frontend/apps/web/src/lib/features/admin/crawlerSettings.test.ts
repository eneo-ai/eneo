import { expect, test } from "vitest";

import {
  CRAWLER_SETTINGS_EDITABLE_FIELDS,
  CRAWLER_SETTINGS_READ_ONLY_OPTIMIZATIONS,
  toCrawlerSettingsUpdate
} from "./crawlerSettings";

test("crawler settings page exposes only user-safe crawler controls", () => {
  const editableKeys = CRAWLER_SETTINGS_EDITABLE_FIELDS.map((field) => field.key);

  expect(editableKeys).toEqual([
    "crawl_sitemap_lastmod_skip_enabled",
    "obey_robots",
    "autothrottle_enabled"
  ]);
  expect(editableKeys).not.toContain("download_timeout");
  expect(editableKeys).not.toContain("crawl_http_cache_enabled");
});

test("hash skip is visible as a built-in optimization, not a mutable setting", () => {
  expect(CRAWLER_SETTINGS_READ_ONLY_OPTIMIZATIONS).toEqual([
    {
      key: "hash_embedding_skip",
      titleKey: "crawler_hash_skip_title",
      descriptionKey: "crawler_hash_skip_description",
      enabled: true
    }
  ]);
});

test("crawler settings update payload is narrowed to editable keys", () => {
  const payload = toCrawlerSettingsUpdate({
    crawl_sitemap_lastmod_skip_enabled: true,
    obey_robots: false,
    autothrottle_enabled: true,
    download_timeout: 120
  });

  expect(payload).toEqual({
    crawl_sitemap_lastmod_skip_enabled: true,
    obey_robots: false,
    autothrottle_enabled: true
  });
});
