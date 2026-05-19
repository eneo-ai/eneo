export const BYTES_PER_MIB = 1024 * 1024;

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

export type CrawlerSettingSpec = {
  type: "int" | "bool";
  description: string;
  min?: number | null;
  max?: number | null;
};

export type CrawlerSettings = {
  tenant_id: string;
  settings: EffectiveCrawlerSettings;
  overrides: string[];
  updated_at?: string | null;
  editable_settings?: string[];
  specs?: Partial<Record<CrawlerSettingsEditableKey, CrawlerSettingSpec>>;
};

export type CrawlerSettingsUpdate = Partial<
  Pick<
    EffectiveCrawlerSettings,
    | "crawl_sitemap_lastmod_skip_enabled"
    | "obey_robots"
    | "autothrottle_enabled"
    | "download_max_size"
    | "download_timeout"
    | "dns_timeout"
    | "retry_times"
    | "closespider_itemcount"
    | "crawl_max_length"
    | "crawl_stale_threshold_minutes"
    | "queued_stale_threshold_minutes"
    | "crawl_heartbeat_interval_seconds"
    | "crawl_job_max_age_seconds"
  >
>;

export type CrawlerSettingsEditableKey = keyof CrawlerSettingsUpdate;
export type CrawlerSettingsBooleanKey =
  | "crawl_sitemap_lastmod_skip_enabled"
  | "obey_robots"
  | "autothrottle_enabled";
export type CrawlerSettingsNumberKey = Exclude<
  CrawlerSettingsEditableKey,
  CrawlerSettingsBooleanKey
>;

export type CrawlerBooleanField = {
  kind: "boolean";
  key: CrawlerSettingsBooleanKey;
  titleKey: string;
  descriptionKey: string;
  warningKey?: string;
};

export type CrawlerNumberField = {
  kind: "number";
  key: CrawlerSettingsNumberKey;
  titleKey: string;
  descriptionKey: string;
  unitKey: string;
  displayUnit: "mib" | "native";
  step: number;
};

export const CRAWLER_SETTINGS_BOOLEAN_FIELDS: CrawlerBooleanField[] = [
  {
    kind: "boolean",
    key: "crawl_sitemap_lastmod_skip_enabled",
    titleKey: "crawler_lastmod_skip_title",
    descriptionKey: "crawler_lastmod_skip_description",
    warningKey: "crawler_lastmod_skip_warning"
  },
  {
    kind: "boolean",
    key: "obey_robots",
    titleKey: "crawler_obey_robots_title",
    descriptionKey: "crawler_obey_robots_description"
  },
  {
    kind: "boolean",
    key: "autothrottle_enabled",
    titleKey: "crawler_autothrottle_title",
    descriptionKey: "crawler_autothrottle_description"
  }
];

export const CRAWLER_SETTINGS_NUMBER_FIELDS: CrawlerNumberField[] = [
  {
    kind: "number",
    key: "download_max_size",
    titleKey: "crawler_download_max_size_title",
    descriptionKey: "crawler_download_max_size_description",
    unitKey: "crawler_unit_mib",
    displayUnit: "mib",
    step: 1
  },
  {
    kind: "number",
    key: "download_timeout",
    titleKey: "crawler_download_timeout_title",
    descriptionKey: "crawler_download_timeout_description",
    unitKey: "crawler_unit_seconds",
    displayUnit: "native",
    step: 1
  },
  {
    kind: "number",
    key: "dns_timeout",
    titleKey: "crawler_dns_timeout_title",
    descriptionKey: "crawler_dns_timeout_description",
    unitKey: "crawler_unit_seconds",
    displayUnit: "native",
    step: 1
  },
  {
    kind: "number",
    key: "retry_times",
    titleKey: "crawler_retry_times_title",
    descriptionKey: "crawler_retry_times_description",
    unitKey: "crawler_unit_attempts",
    displayUnit: "native",
    step: 1
  },
  {
    kind: "number",
    key: "closespider_itemcount",
    titleKey: "crawler_closespider_itemcount_title",
    descriptionKey: "crawler_closespider_itemcount_description",
    unitKey: "crawler_unit_items",
    displayUnit: "native",
    step: 100
  },
  // Values are read at crawl start, so changes do not affect already-running
  // crawls; each new crawl picks up the updated value. Bounds come from the
  // backend specs via the response so the API boundary stays authoritative.
  {
    kind: "number",
    key: "crawl_max_length",
    titleKey: "crawler_max_length_title",
    descriptionKey: "crawler_max_length_description",
    unitKey: "crawler_unit_seconds",
    displayUnit: "native",
    step: 60
  },
  {
    kind: "number",
    key: "crawl_stale_threshold_minutes",
    titleKey: "crawler_stale_threshold_title",
    descriptionKey: "crawler_stale_threshold_description",
    unitKey: "crawler_unit_minutes",
    displayUnit: "native",
    step: 1
  },
  {
    kind: "number",
    key: "queued_stale_threshold_minutes",
    titleKey: "crawler_queued_stale_title",
    descriptionKey: "crawler_queued_stale_description",
    unitKey: "crawler_unit_minutes",
    displayUnit: "native",
    step: 1
  },
  {
    kind: "number",
    key: "crawl_heartbeat_interval_seconds",
    titleKey: "crawler_heartbeat_interval_title",
    descriptionKey: "crawler_heartbeat_interval_description",
    unitKey: "crawler_unit_seconds",
    displayUnit: "native",
    step: 10
  },
  {
    kind: "number",
    key: "crawl_job_max_age_seconds",
    titleKey: "crawler_job_max_age_title",
    descriptionKey: "crawler_job_max_age_description",
    unitKey: "crawler_unit_seconds",
    displayUnit: "native",
    step: 60
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

export type CrawlerNumberValidation =
  | { valid: true; canonicalValue: number }
  | {
      valid: false;
      reason: "not_integer" | "below_min" | "above_max";
      min?: number;
      max?: number;
    };

export function getCrawlerSettingDisplayValue(
  key: CrawlerSettingsNumberKey,
  value: number
): number {
  return key === "download_max_size" ? value / BYTES_PER_MIB : value;
}

export function getCrawlerSettingDisplayBounds(
  field: CrawlerNumberField,
  specs: CrawlerSettings["specs"]
): { min?: number; max?: number } {
  const spec = specs?.[field.key];
  const min = typeof spec?.min === "number" ? spec.min : undefined;
  const max = typeof spec?.max === "number" ? spec.max : undefined;

  if (field.displayUnit === "mib") {
    return {
      min: min === undefined ? undefined : getCrawlerSettingDisplayValue(field.key, min),
      max: max === undefined ? undefined : getCrawlerSettingDisplayValue(field.key, max)
    };
  }

  return { min, max };
}

export function validateCrawlerNumberField(
  field: CrawlerNumberField,
  value: unknown,
  specs: CrawlerSettings["specs"]
): CrawlerNumberValidation {
  const numericValue = typeof value === "string" && value.trim() !== "" ? Number(value) : value;

  if (typeof numericValue !== "number" || !Number.isFinite(numericValue)) {
    return { valid: false, reason: "not_integer" };
  }

  if (!Number.isInteger(numericValue)) {
    return { valid: false, reason: "not_integer" };
  }

  const canonicalValue = field.displayUnit === "mib" ? numericValue * BYTES_PER_MIB : numericValue;
  const spec = specs?.[field.key];
  const min = typeof spec?.min === "number" ? spec.min : undefined;
  const max = typeof spec?.max === "number" ? spec.max : undefined;

  if (min !== undefined && canonicalValue < min) {
    return {
      valid: false,
      reason: "below_min",
      min: getCrawlerSettingDisplayBounds(field, specs).min
    };
  }

  if (max !== undefined && canonicalValue > max) {
    return {
      valid: false,
      reason: "above_max",
      max: getCrawlerSettingDisplayBounds(field, specs).max
    };
  }

  return { valid: true, canonicalValue };
}

export function toCrawlerSettingsUpdate(
  values: Record<string, unknown>,
  specs?: CrawlerSettings["specs"]
): CrawlerSettingsUpdate {
  const update: CrawlerSettingsUpdate = {};

  for (const field of CRAWLER_SETTINGS_BOOLEAN_FIELDS) {
    const value = values[field.key];
    if (typeof value === "boolean") {
      update[field.key] = value;
    }
  }

  for (const field of CRAWLER_SETTINGS_NUMBER_FIELDS) {
    const validation = validateCrawlerNumberField(field, values[field.key], specs);
    if (validation.valid) {
      update[field.key] = validation.canonicalValue;
    }
  }

  return update;
}
