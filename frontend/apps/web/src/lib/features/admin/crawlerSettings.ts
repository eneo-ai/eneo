export type EffectiveCrawlerSettings = {
  crawl_max_length: number;
  download_timeout: number;
  download_max_size: number;
  dns_timeout: number;
  retry_times: number;
  closespider_itemcount: number;
  obey_robots: boolean;
  autothrottle_enabled: boolean;
  tenant_worker_concurrency_limit: number;
  crawl_stale_threshold_minutes: number;
  queued_stale_threshold_minutes: number;
  crawl_heartbeat_interval_seconds: number;
  crawl_feeder_enabled: boolean;
  crawl_feeder_interval_seconds: number;
  crawl_feeder_batch_size: number;
  crawl_job_max_age_seconds: number;
  tenant_worker_semaphore_ttl_seconds: number;
  crawl_page_batch_size: number;
  crawl_sitemap_lastmod_skip_enabled: boolean;
};

export type CrawlerSettings = {
  tenant_id: string;
  settings: EffectiveCrawlerSettings;
  overrides: string[];
  updated_at?: string | null;
};

export type CrawlerSettingsUpdate = Partial<
  Pick<
    EffectiveCrawlerSettings,
    "crawl_sitemap_lastmod_skip_enabled" | "obey_robots" | "autothrottle_enabled"
  >
>;

export type CrawlerSettingsEditableKey = keyof CrawlerSettingsUpdate;

export type CrawlerSettingsField = {
  key: CrawlerSettingsEditableKey;
  titleKey: string;
  descriptionKey: string;
  warningKey?: string;
};

export const CRAWLER_SETTINGS_EDITABLE_FIELDS: CrawlerSettingsField[] = [
  {
    key: "crawl_sitemap_lastmod_skip_enabled",
    titleKey: "crawler_lastmod_skip_title",
    descriptionKey: "crawler_lastmod_skip_description",
    warningKey: "crawler_lastmod_skip_warning"
  },
  {
    key: "obey_robots",
    titleKey: "crawler_obey_robots_title",
    descriptionKey: "crawler_obey_robots_description"
  },
  {
    key: "autothrottle_enabled",
    titleKey: "crawler_autothrottle_title",
    descriptionKey: "crawler_autothrottle_description"
  }
];

export type CrawlerReadOnlyOptimization = {
  key: "hash_embedding_skip";
  titleKey: string;
  descriptionKey: string;
  enabled: true;
};

export const CRAWLER_SETTINGS_READ_ONLY_OPTIMIZATIONS: CrawlerReadOnlyOptimization[] = [
  {
    key: "hash_embedding_skip",
    titleKey: "crawler_hash_skip_title",
    descriptionKey: "crawler_hash_skip_description",
    enabled: true
  }
];

export function toCrawlerSettingsUpdate(values: Record<string, unknown>): CrawlerSettingsUpdate {
  const update: CrawlerSettingsUpdate = {};

  for (const field of CRAWLER_SETTINGS_EDITABLE_FIELDS) {
    const value = values[field.key];
    if (typeof value === "boolean") {
      update[field.key] = value;
    }
  }

  return update;
}
