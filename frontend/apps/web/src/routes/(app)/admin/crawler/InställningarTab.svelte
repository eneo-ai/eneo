<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0).
    See the LICENSE file at the repository root for the full license text.
-->

<script lang="ts">
  import { invalidate } from "$app/navigation";
  import { fly } from "svelte/transition";
  import { quintOut } from "svelte/easing";
  import { toast } from "$lib/components/toast";
  import { toastError } from "$lib/core/errors";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import * as InputGroup from "$lib/components/ui/input-group/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { Settings } from "$lib/components/layout";
  import { ShieldCheck, TriangleAlert } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import type { Intric } from "@intric/intric-js";
  import {
    CRAWLER_SETTINGS_BOOLEAN_FIELDS,
    CRAWLER_SETTINGS_NUMBER_FIELDS,
    CRAWLER_SETTINGS_READ_ONLY_OPTIMIZATIONS,
    getCrawlerSettingDisplayBounds,
    getCrawlerSettingDisplayValue,
    toCrawlerSettingsUpdate,
    validateCrawlerNumberField,
    type CrawlerNumberField,
    type CrawlerSettings,
    type CrawlerSettingsEditableKey,
    type CrawlerSettingsUpdate
  } from "$lib/features/admin/crawlerSettings";

  type CrawlerSettingsFormValue = boolean | number | string;
  type CrawlerSettingsFormValues = Record<CrawlerSettingsEditableKey, CrawlerSettingsFormValue>;

  type Props = {
    initialCrawlerSettings: CrawlerSettings;
    intric: Intric;
  };

  const { initialCrawlerSettings, intric }: Props = $props();

  // Local state owned by this tab. Reset whenever the SSR payload
  // changes (e.g. invalidate after a save).
  let crawlerSettings = $state<CrawlerSettings | null>(null);
  let formValues = $state<CrawlerSettingsFormValues>(emptyFormValues());
  let savedValues = $state<CrawlerSettingsFormValues>(emptyFormValues());
  let savingKey = $state<CrawlerSettingsEditableKey | null>(null);
  let savingAllSettings = $state<boolean>(false);

  // Pre-effect: sync the form state from the SSR payload before
  // first paint so the inputs are populated immediately.
  $effect.pre(() => {
    syncCrawlerSettings(initialCrawlerSettings);
  });

  // Memoised message-getter map keeps the resolution at the locale
  // boundary that other markup uses (avoids spreading m.* calls
  // across the row markup).
  const fieldTextByKey: Record<string, () => string> = {
    crawler_hash_skip_title: () => m.crawler_hash_skip_title(),
    crawler_hash_skip_description: () => m.crawler_hash_skip_description(),
    crawler_lastmod_skip_title: () => m.crawler_lastmod_skip_title(),
    crawler_lastmod_skip_description: () => m.crawler_lastmod_skip_description(),
    crawler_lastmod_skip_warning: () => m.crawler_lastmod_skip_warning(),
    crawler_obey_robots_title: () => m.crawler_obey_robots_title(),
    crawler_obey_robots_description: () => m.crawler_obey_robots_description(),
    crawler_autothrottle_title: () => m.crawler_autothrottle_title(),
    crawler_autothrottle_description: () => m.crawler_autothrottle_description(),
    crawler_download_max_size_title: () => m.crawler_download_max_size_title(),
    crawler_download_max_size_description: () => m.crawler_download_max_size_description(),
    crawler_download_timeout_title: () => m.crawler_download_timeout_title(),
    crawler_download_timeout_description: () => m.crawler_download_timeout_description(),
    crawler_dns_timeout_title: () => m.crawler_dns_timeout_title(),
    crawler_dns_timeout_description: () => m.crawler_dns_timeout_description(),
    crawler_retry_times_title: () => m.crawler_retry_times_title(),
    crawler_retry_times_description: () => m.crawler_retry_times_description(),
    crawler_closespider_itemcount_title: () => m.crawler_closespider_itemcount_title(),
    crawler_closespider_itemcount_description: () => m.crawler_closespider_itemcount_description(),
    crawler_max_length_title: () => m.crawler_max_length_title(),
    crawler_max_length_description: () => m.crawler_max_length_description(),
    crawler_stale_threshold_title: () => m.crawler_stale_threshold_title(),
    crawler_stale_threshold_description: () => m.crawler_stale_threshold_description(),
    crawler_queued_stale_title: () => m.crawler_queued_stale_title(),
    crawler_queued_stale_description: () => m.crawler_queued_stale_description(),
    crawler_heartbeat_interval_title: () => m.crawler_heartbeat_interval_title(),
    crawler_heartbeat_interval_description: () => m.crawler_heartbeat_interval_description(),
    crawler_job_max_age_title: () => m.crawler_job_max_age_title(),
    crawler_job_max_age_description: () => m.crawler_job_max_age_description(),
    crawler_unit_mib: () => m.crawler_unit_mib(),
    crawler_unit_seconds: () => m.crawler_unit_seconds(),
    crawler_unit_minutes: () => m.crawler_unit_minutes(),
    crawler_unit_attempts: () => m.crawler_unit_attempts(),
    crawler_unit_items: () => m.crawler_unit_items()
  };

  function fieldText(key: string): string {
    return fieldTextByKey[key]?.() ?? key;
  }

  function emptyFormValues(): CrawlerSettingsFormValues {
    return {
      crawl_sitemap_lastmod_skip_enabled: false,
      obey_robots: false,
      autothrottle_enabled: false,
      download_max_size: 0,
      download_timeout: 0,
      dns_timeout: 0,
      retry_times: 0,
      closespider_itemcount: 0,
      crawl_max_length: 0,
      crawl_stale_threshold_minutes: 0,
      queued_stale_threshold_minutes: 0,
      crawl_heartbeat_interval_seconds: 0,
      crawl_job_max_age_seconds: 0
    };
  }

  function buildFormValues(source: CrawlerSettings): CrawlerSettingsFormValues {
    const settings = source.settings;
    return {
      crawl_sitemap_lastmod_skip_enabled: settings.crawl_sitemap_lastmod_skip_enabled,
      obey_robots: settings.obey_robots,
      autothrottle_enabled: settings.autothrottle_enabled,
      download_max_size: getCrawlerSettingDisplayValue(
        "download_max_size",
        settings.download_max_size
      ),
      download_timeout: settings.download_timeout,
      dns_timeout: settings.dns_timeout,
      retry_times: settings.retry_times,
      closespider_itemcount: settings.closespider_itemcount,
      crawl_max_length: settings.crawl_max_length,
      crawl_stale_threshold_minutes: settings.crawl_stale_threshold_minutes,
      queued_stale_threshold_minutes: settings.queued_stale_threshold_minutes,
      crawl_heartbeat_interval_seconds: settings.crawl_heartbeat_interval_seconds,
      crawl_job_max_age_seconds: settings.crawl_job_max_age_seconds
    };
  }

  function syncCrawlerSettings(updatedCrawlerSettings: CrawlerSettings): void {
    const nextValues = buildFormValues(updatedCrawlerSettings);
    crawlerSettings = updatedCrawlerSettings;
    formValues = nextValues;
    savedValues = { ...nextValues };
  }

  function rangeHint(field: CrawlerNumberField): string | null {
    const bounds = getCrawlerSettingDisplayBounds(field, crawlerSettings?.specs);
    if (bounds.min === undefined || bounds.max === undefined) return null;
    return m.crawler_setting_range({
      min: bounds.min,
      max: bounds.max,
      unit: fieldText(field.unitKey)
    });
  }

  function numericError(field: CrawlerNumberField): string | null {
    const validation = validateCrawlerNumberField(
      field,
      formValues[field.key],
      crawlerSettings?.specs
    );
    if (validation.valid) return null;
    if (validation.reason === "below_min" && validation.min !== undefined) {
      return m.crawler_setting_min_value({
        min: validation.min,
        unit: fieldText(field.unitKey)
      });
    }
    if (validation.reason === "above_max" && validation.max !== undefined) {
      return m.crawler_setting_max_value({
        max: validation.max,
        unit: fieldText(field.unitKey)
      });
    }
    return m.crawler_setting_invalid_integer();
  }

  function fieldIsDirty(key: CrawlerSettingsEditableKey): boolean {
    return String(formValues[key]) !== String(savedValues[key]);
  }

  function resetField(key: CrawlerSettingsEditableKey): void {
    formValues[key] = savedValues[key];
  }

  // F: batched settings save state.
  const dirtyNumberFieldKeys = $derived(
    CRAWLER_SETTINGS_NUMBER_FIELDS.filter((field) => fieldIsDirty(field.key)).map(
      (field) => field.key
    )
  );
  const hasNumberFieldErrors = $derived(
    CRAWLER_SETTINGS_NUMBER_FIELDS.some((field) => Boolean(numericError(field)))
  );

  async function saveCrawlerSettings(
    update: CrawlerSettingsUpdate,
    key: CrawlerSettingsEditableKey
  ): Promise<void> {
    savingKey = key;
    try {
      const updatedSettings = await intric.settings.updateCrawler(update);
      syncCrawlerSettings(updatedSettings as CrawlerSettings);
      await invalidate("admin:crawler-settings");
      toast.success(m.crawler_settings_saved());
    } catch (error) {
      resetField(key);
      toastError(error, m.could_not_update_crawler_settings());
    } finally {
      savingKey = null;
    }
  }

  async function handleToggleCrawlerSetting(
    key: CrawlerSettingsEditableKey,
    next: boolean
  ): Promise<void> {
    const current = formValues[key];
    formValues[key] = next;
    const update = toCrawlerSettingsUpdate({ [key]: next }, crawlerSettings?.specs);
    if (Object.keys(update).length === 0) {
      formValues[key] = current;
      return;
    }
    await saveCrawlerSettings(update, key);
  }

  async function handleSaveAllNumberSettings(): Promise<void> {
    if (dirtyNumberFieldKeys.length === 0 || hasNumberFieldErrors) return;
    savingAllSettings = true;
    try {
      const partial: Partial<Record<CrawlerSettingsEditableKey, CrawlerSettingsFormValue>> = {};
      for (const key of dirtyNumberFieldKeys) {
        partial[key] = formValues[key];
      }
      const update = toCrawlerSettingsUpdate(partial, crawlerSettings?.specs);
      if (Object.keys(update).length === 0) return;
      const updatedSettings = await intric.settings.updateCrawler(update);
      syncCrawlerSettings(updatedSettings as CrawlerSettings);
      await invalidate("admin:crawler-settings");
      toast.success(m.crawler_settings_save_all_success());
    } catch (error) {
      for (const key of dirtyNumberFieldKeys) {
        resetField(key);
      }
      toastError(error, m.could_not_update_crawler_settings());
    } finally {
      savingAllSettings = false;
    }
  }

  function handleResetAllNumberSettings(): void {
    for (const key of dirtyNumberFieldKeys) {
      resetField(key);
    }
  }
</script>

<Card.Root class="mb-14" aria-labelledby="crawler-builtin-card-title">
  <Card.Header>
    <div class="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
      <div class="flex min-w-0 flex-col gap-1">
        <h2 id="crawler-builtin-card-title" class="text-base leading-snug font-semibold">
          {m.crawler_builtin_card_title()}
        </h2>
        <Card.Description>{m.crawler_builtin_card_description()}</Card.Description>
      </div>
      <Badge variant="default" class="shrink-0">
        {m.crawler_built_in_badge()}
      </Badge>
    </div>
  </Card.Header>
  <Card.Content class="flex flex-col gap-2 pt-0">
    {#each CRAWLER_SETTINGS_READ_ONLY_OPTIMIZATIONS as optimization (optimization.key)}
      <div class="flex items-start gap-3">
        <ShieldCheck class="text-accent-default mt-0.5 size-5 shrink-0" aria-hidden="true" />
        <div class="flex min-w-0 flex-col gap-1">
          <h3 class="text-sm font-medium">{fieldText(optimization.titleKey)}</h3>
          <p class="text-muted-foreground text-sm leading-relaxed">
            {fieldText(optimization.descriptionKey)}
          </p>
        </div>
      </div>
    {/each}
  </Card.Content>
</Card.Root>

<Settings.Group title={m.crawler_controls()}>
  <p class="text-secondary -mt-2 max-w-[64ch] pr-12 pl-2 text-sm leading-relaxed">
    {m.crawler_controls_subtitle()}
  </p>

  {#each CRAWLER_SETTINGS_BOOLEAN_FIELDS as field (field.key)}
    <Settings.Row title={fieldText(field.titleKey)} description={fieldText(field.descriptionKey)}>
      <div slot="description">
        {#if field.warningKey}
          <Alert.Root class="border-caution/35 bg-caution/8 dark:bg-caution/12 mt-2">
            <TriangleAlert class="text-caution" aria-hidden="true" />
            <Alert.Description class="text-caution">
              {fieldText(field.warningKey)}
            </Alert.Description>
          </Alert.Root>
        {/if}
      </div>
      <div class="flex items-center justify-end pt-1">
        <Switch
          checked={Boolean(formValues[field.key])}
          onCheckedChange={(next) => void handleToggleCrawlerSetting(field.key, next)}
          disabled={savingKey === field.key}
          aria-label={fieldText(field.titleKey)}
        />
      </div>
    </Settings.Row>
  {/each}
</Settings.Group>

<Settings.Group title={m.crawler_limits()}>
  <p class="text-secondary -mt-2 max-w-[64ch] pr-12 pl-2 text-sm leading-relaxed">
    {m.crawler_limits_subtitle()}
  </p>

  {#each CRAWLER_SETTINGS_NUMBER_FIELDS as field (field.key)}
    {@const error = numericError(field)}
    {@const bounds = getCrawlerSettingDisplayBounds(field, crawlerSettings?.specs)}
    {@const range = rangeHint(field)}
    {@const isDirty = fieldIsDirty(field.key)}
    {@const isSaving = savingKey === field.key}
    <Settings.Row title={fieldText(field.titleKey)} description={fieldText(field.descriptionKey)}>
      <Field.Field data-invalid={error ? "true" : undefined}>
        <Field.Label for={`crawler-setting-${field.key}`} class="sr-only">
          {fieldText(field.titleKey)}
        </Field.Label>
        <div class="flex flex-wrap items-start justify-end gap-2">
          <div class="flex flex-col items-end gap-1">
            <InputGroup.Root class="w-44">
              <InputGroup.Input
                id={`crawler-setting-${field.key}`}
                type="number"
                value={formValues[field.key]}
                min={bounds.min}
                max={bounds.max}
                step={field.step}
                aria-invalid={Boolean(error)}
                disabled={isSaving}
                oninput={(event) => {
                  formValues[field.key] = event.currentTarget.value;
                }}
              />
              <InputGroup.Addon align="inline-end">
                {fieldText(field.unitKey)}
              </InputGroup.Addon>
            </InputGroup.Root>
            {#if range && !error}
              <span class="text-muted-foreground text-xs tabular-nums">
                {range}
              </span>
            {/if}
          </div>
          {#if isDirty && !isSaving}
            <span
              class="bg-accent-default/15 text-accent-default rounded-full px-2 py-0.5 text-[10px] font-medium tracking-wide uppercase"
              aria-hidden="true"
            >
              •
            </span>
          {/if}
        </div>
        {#if error}
          <Field.Error class="text-right">{error}</Field.Error>
        {/if}
      </Field.Field>
    </Settings.Row>
  {/each}
</Settings.Group>

{#if dirtyNumberFieldKeys.length > 0}
  <div
    class="border-border bg-frosted-glass-primary/95 sticky bottom-4 mx-2 mt-6 flex flex-wrap items-center justify-between gap-3 rounded-xl border px-4 py-3 shadow-lg backdrop-blur"
    role="region"
    aria-label={m.crawler_settings_save_all()}
    transition:fly={{ y: 16, duration: 220, easing: quintOut }}
  >
    <span class="text-foreground text-sm font-medium">
      {dirtyNumberFieldKeys.length === 1
        ? m.crawler_settings_unsaved_count_one()
        : m.crawler_settings_unsaved_count_other({
            count: String(dirtyNumberFieldKeys.length)
          })}
    </span>
    <div class="flex items-center gap-2">
      <Button
        variant="ghost"
        size="sm"
        onclick={handleResetAllNumberSettings}
        disabled={savingAllSettings}
      >
        {m.crawler_settings_reset_all()}
      </Button>
      <Button
        size="sm"
        disabled={savingAllSettings || hasNumberFieldErrors}
        onclick={() => void handleSaveAllNumberSettings()}
      >
        {savingAllSettings ? m.crawler_settings_save_all_busy() : m.crawler_settings_save_all()}
      </Button>
    </div>
  </div>
{/if}
