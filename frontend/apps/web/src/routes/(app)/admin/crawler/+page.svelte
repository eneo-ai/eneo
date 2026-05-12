<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { invalidate } from "$app/navigation";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import * as InputGroup from "$lib/components/ui/input-group/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { Page, Settings } from "$lib/components/layout";
  import { toast } from "$lib/components/toast";
  import { getIntric } from "$lib/core/Intric.js";
  import { toastError } from "$lib/core/errors";
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
  import { m } from "$lib/paraglide/messages";
  import { Gauge } from "lucide-svelte";

  type CrawlerSettingsFormValue = boolean | number | string;
  type CrawlerSettingsFormValues = Record<CrawlerSettingsEditableKey, CrawlerSettingsFormValue>;

  const intric = getIntric();
  let { data }: { data: { crawlerSettings: CrawlerSettings } } = $props();

  let crawlerSettings = $state<CrawlerSettings | null>(null);
  let formValues = $state<CrawlerSettingsFormValues>(emptyFormValues());
  let savedValues = $state<CrawlerSettingsFormValues>(emptyFormValues());
  let savingKey = $state<CrawlerSettingsEditableKey | null>(null);

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
    crawler_unit_mib: () => m.crawler_unit_mib(),
    crawler_unit_seconds: () => m.crawler_unit_seconds(),
    crawler_unit_attempts: () => m.crawler_unit_attempts(),
    crawler_unit_items: () => m.crawler_unit_items()
  };

  $effect.pre(() => {
    syncCrawlerSettings(data.crawlerSettings);
  });

  function emptyFormValues(): CrawlerSettingsFormValues {
    return {
      crawl_sitemap_lastmod_skip_enabled: false,
      obey_robots: false,
      autothrottle_enabled: false,
      download_max_size: 0,
      download_timeout: 0,
      dns_timeout: 0,
      retry_times: 0,
      closespider_itemcount: 0
    };
  }

  function buildFormValues(crawlerSettings: CrawlerSettings): CrawlerSettingsFormValues {
    const settings = crawlerSettings.settings;

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
      closespider_itemcount: settings.closespider_itemcount
    };
  }

  function syncCrawlerSettings(updatedCrawlerSettings: CrawlerSettings) {
    const nextValues = buildFormValues(updatedCrawlerSettings);
    crawlerSettings = updatedCrawlerSettings;
    formValues = nextValues;
    savedValues = { ...nextValues };
  }

  function fieldText(key: string) {
    return fieldTextByKey[key]?.() ?? key;
  }

  function fieldDescription(field: { descriptionKey: string; warningKey?: string }) {
    const description = fieldText(field.descriptionKey);
    return field.warningKey ? `${description}\n${fieldText(field.warningKey)}` : description;
  }

  function numericError(field: CrawlerNumberField) {
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

  function fieldIsDirty(key: CrawlerSettingsEditableKey) {
    return String(formValues[key]) !== String(savedValues[key]);
  }

  function resetField(key: CrawlerSettingsEditableKey) {
    formValues[key] = savedValues[key];
  }

  async function saveCrawlerSettings(
    update: CrawlerSettingsUpdate,
    key: CrawlerSettingsEditableKey
  ) {
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

  async function handleToggleCrawlerSetting(key: CrawlerSettingsEditableKey, next: boolean) {
    const current = formValues[key];
    formValues[key] = next;

    const update = toCrawlerSettingsUpdate({ [key]: next }, crawlerSettings?.specs);
    if (Object.keys(update).length === 0) {
      formValues[key] = current;
      return;
    }

    await saveCrawlerSettings(update, key);
  }

  async function handleSaveNumberSetting(field: CrawlerNumberField) {
    const error = numericError(field);
    if (error) {
      toast.error(error);
      return;
    }

    const update = toCrawlerSettingsUpdate(
      { [field.key]: formValues[field.key] },
      crawlerSettings?.specs
    );
    if (Object.keys(update).length === 0) return;

    await saveCrawlerSettings(update, field.key);
  }
</script>

<svelte:head>
  <title>Eneo.ai - {m.crawler_settings()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.crawler_settings()} />
  </Page.Header>
  <Page.Main>
    <Settings.Page>
      <Settings.Group title={m.crawler_optimizations()}>
        {#each CRAWLER_SETTINGS_READ_ONLY_OPTIMIZATIONS as optimization (optimization.key)}
          <Settings.Row
            title={fieldText(optimization.titleKey)}
            description={fieldText(optimization.descriptionKey)}
          >
            <div class="flex items-center justify-end pt-2">
              <span
                class="border-dimmer bg-secondary text-secondary inline-flex items-center gap-2 rounded-md border px-3 py-1 text-sm"
              >
                <Gauge class="h-4 w-4" />
                {m.active()}
              </span>
            </div>
          </Settings.Row>
        {/each}
      </Settings.Group>

      <Settings.Group title={m.crawler_controls()}>
        {#each CRAWLER_SETTINGS_BOOLEAN_FIELDS as field (field.key)}
          <Settings.Row title={fieldText(field.titleKey)} description={fieldDescription(field)}>
            <Switch
              checked={Boolean(formValues[field.key])}
              onCheckedChange={(next) => void handleToggleCrawlerSetting(field.key, next)}
              disabled={savingKey === field.key}
              aria-label={fieldText(field.titleKey)}
            />
          </Settings.Row>
        {/each}
      </Settings.Group>

      <Settings.Group title={m.crawler_limits()}>
        {#each CRAWLER_SETTINGS_NUMBER_FIELDS as field (field.key)}
          {@const error = numericError(field)}
          {@const bounds = getCrawlerSettingDisplayBounds(field, crawlerSettings?.specs)}
          <Settings.Row
            title={fieldText(field.titleKey)}
            description={fieldText(field.descriptionKey)}
          >
            <Field.Field data-invalid={error ? "true" : undefined}>
              <Field.Label for={`crawler-setting-${field.key}`} class="sr-only">
                {fieldText(field.titleKey)}
              </Field.Label>
              <div class="flex flex-wrap items-start justify-end gap-2">
                <InputGroup.Root class="w-44">
                  <InputGroup.Input
                    id={`crawler-setting-${field.key}`}
                    type="number"
                    value={formValues[field.key]}
                    min={bounds.min}
                    max={bounds.max}
                    step={field.step}
                    aria-invalid={Boolean(error)}
                    disabled={savingKey === field.key}
                    oninput={(event) => {
                      formValues[field.key] = event.currentTarget.value;
                    }}
                  />
                  <InputGroup.Addon align="inline-end">
                    {fieldText(field.unitKey)}
                  </InputGroup.Addon>
                </InputGroup.Root>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={!fieldIsDirty(field.key) || savingKey === field.key}
                  onclick={() => resetField(field.key)}
                >
                  {m.reset()}
                </Button>
                <Button
                  size="sm"
                  disabled={!fieldIsDirty(field.key) || Boolean(error) || savingKey === field.key}
                  onclick={() => void handleSaveNumberSetting(field)}
                >
                  {m.save()}
                </Button>
              </div>
              {#if error}
                <Field.Error class="text-right">{error}</Field.Error>
              {/if}
            </Field.Field>
          </Settings.Row>
        {/each}
      </Settings.Group>
    </Settings.Page>
  </Page.Main>
</Page.Root>
