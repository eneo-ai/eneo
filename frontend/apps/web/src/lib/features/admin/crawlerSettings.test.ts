import { expect, test } from "vitest";

import {
  BYTES_PER_MIB,
  CRAWLER_SETTINGS_BOOLEAN_FIELDS,
  CRAWLER_SETTINGS_NUMBER_FIELDS,
  CRAWLER_SETTINGS_READ_ONLY_OPTIMIZATIONS,
  getCrawlerSettingDisplayValue,
  toCrawlerSettingsUpdate
} from "./crawlerSettings";

const specs = {
  crawl_sitemap_lastmod_skip_enabled: { type: "bool", description: "" },
  obey_robots: { type: "bool", description: "" },
  autothrottle_enabled: { type: "bool", description: "" },
  download_max_size: {
    type: "int",
    min: 1 * BYTES_PER_MIB,
    max: 1024 * BYTES_PER_MIB,
    description: ""
  },
  download_timeout: { type: "int", min: 10, max: 300, description: "" },
  dns_timeout: { type: "int", min: 5, max: 120, description: "" },
  retry_times: { type: "int", min: 0, max: 10, description: "" },
  closespider_itemcount: { type: "int", min: 100, max: 100_000, description: "" }
} as const;

test("crawler settings page exposes only user-safe crawler controls", () => {
  const editableKeys = [
    ...CRAWLER_SETTINGS_BOOLEAN_FIELDS.map((field) => field.key),
    ...CRAWLER_SETTINGS_NUMBER_FIELDS.map((field) => field.key)
  ];

  expect(editableKeys).toEqual([
    "crawl_sitemap_lastmod_skip_enabled",
    "obey_robots",
    "autothrottle_enabled",
    "download_max_size",
    "download_timeout",
    "dns_timeout",
    "retry_times",
    "closespider_itemcount"
  ]);
  expect(editableKeys).not.toContain("crawl_max_length");
  expect(editableKeys).not.toContain("crawl_page_batch_size");
  expect(editableKeys).not.toContain("tenant_worker_concurrency_limit");
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
  const payload = toCrawlerSettingsUpdate(
    {
      crawl_sitemap_lastmod_skip_enabled: true,
      obey_robots: false,
      autothrottle_enabled: true,
      download_max_size: "50",
      download_timeout: "120",
      dns_timeout: 45,
      retry_times: 3,
      closespider_itemcount: 5_000,
      crawl_max_length: 7200,
      crawl_page_batch_size: 200,
      tenant_worker_concurrency_limit: 10
    },
    specs
  );

  expect(payload).toEqual({
    crawl_sitemap_lastmod_skip_enabled: true,
    obey_robots: false,
    autothrottle_enabled: true,
    download_max_size: 50 * BYTES_PER_MIB,
    download_timeout: 120,
    dns_timeout: 45,
    retry_times: 3,
    closespider_itemcount: 5_000
  });
});

test("crawler settings display values use admin-friendly units", () => {
  expect(getCrawlerSettingDisplayValue("download_max_size", 1 * BYTES_PER_MIB)).toBe(1);
  expect(getCrawlerSettingDisplayValue("download_max_size", 1024 * BYTES_PER_MIB)).toBe(1024);
  expect(getCrawlerSettingDisplayValue("download_timeout", 120)).toBe(120);
});

test("crawler settings update excludes invalid numeric values", () => {
  const payload = toCrawlerSettingsUpdate(
    {
      download_max_size: 0,
      download_timeout: 301,
      dns_timeout: "not-a-number",
      retry_times: 2,
      closespider_itemcount: 10
    },
    specs
  );

  expect(payload).toEqual({ retry_times: 2 });
});
