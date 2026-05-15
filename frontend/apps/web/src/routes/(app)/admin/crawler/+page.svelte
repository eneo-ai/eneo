<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { invalidate } from "$app/navigation";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import * as InputGroup from "$lib/components/ui/input-group/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
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
  import {
    getCrawlerActiveInventoryResultLabels,
    getCrawlerActiveInventoryStatusLabel,
    getCrawlerActiveInventoryWebsiteLabel,
    type CrawlerActiveInventoryItem,
    type CrawlerActiveInventoryResponse
  } from "$lib/features/admin/crawlerActiveInventory";
  import type { CrawlRunResultLabel } from "$lib/features/knowledge/crawlOutcomePresentation";
  import {
    getCrawlerRecentFailureOutcomeLabel,
    getCrawlerRecentFailureResultLabels,
    getCrawlerRecentFailureWebsiteLabel,
    type CrawlerRecentFailuresResponse
  } from "$lib/features/admin/crawlerRecentFailures";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import { ShieldCheck, TriangleAlert } from "lucide-svelte";

  type CrawlerSettingsFormValue = boolean | number | string;
  type CrawlerSettingsFormValues = Record<CrawlerSettingsEditableKey, CrawlerSettingsFormValue>;

  const intric = getIntric();
  let {
    data
  }: {
    data: {
      crawlerSettings: CrawlerSettings;
      crawlerActiveInventory: CrawlerActiveInventoryResponse | null;
      crawlerActiveInventoryLoadFailed: boolean;
      crawlerRecentFailuresWindowDays: number;
      crawlerRecentFailures: CrawlerRecentFailuresResponse | null;
      crawlerRecentFailuresLoadFailed: boolean;
    };
  } = $props();

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

  function formatDateTime(value: string) {
    return new Date(value).toLocaleString(getLocale(), {
      dateStyle: "medium",
      timeStyle: "short"
    });
  }

  function resultBadgeClass(color: CrawlRunResultLabel["color"]) {
    if (color === "orange") {
      return "border-caution/40 bg-caution/8 text-caution";
    }
    if (color === "green") {
      return "border-positive-default/40 bg-positive-dimmer text-positive-stronger";
    }
    if (color === "moss") {
      return "border-success/40 bg-secondary text-success";
    }
    if (color === "blue") {
      return "border-accent-default/35 text-accent-default";
    }
    return undefined;
  }

  function activeStatusBadgeClass(lifecycleState: CrawlerActiveInventoryItem["lifecycle_state"]) {
    switch (lifecycleState) {
      case "running_with_progress":
        return "border-positive-default/40 bg-positive-dimmer text-positive-stronger";
      case "running_no_progress":
      case "terminal":
        return "border-caution/40 bg-caution/8 text-caution";
      case "queued":
        return "border-accent-default/35 text-accent-default";
      default: {
        const exhaustive: never = lifecycleState;
        return exhaustive;
      }
    }
  }

  function rangeHint(field: CrawlerNumberField) {
    const bounds = getCrawlerSettingDisplayBounds(field, crawlerSettings?.specs);
    if (bounds.min === undefined || bounds.max === undefined) return null;
    return m.crawler_setting_range({
      min: bounds.min,
      max: bounds.max,
      unit: fieldText(field.unitKey)
    });
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
      <p class="text-secondary -mt-4 mb-10 max-w-[64ch] pr-12 pl-2 text-[15px] leading-relaxed">
        {m.crawler_settings_subtitle()}
      </p>

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

      <Card.Root class="mb-14" aria-labelledby="crawler-active-inventory-title">
        <Card.Header>
          <div class="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
            <div class="flex min-w-0 flex-col gap-1">
              <h2 id="crawler-active-inventory-title" class="text-base leading-snug font-semibold">
                {m.crawler_active_inventory_title()}
              </h2>
              <Card.Description>{m.crawler_active_inventory_description()}</Card.Description>
            </div>
            {#if data.crawlerActiveInventory}
              <Badge variant="outline" class="shrink-0 tabular-nums">
                {m.crawler_active_inventory_count({
                  shown: data.crawlerActiveInventory.items.length,
                  total: data.crawlerActiveInventory.total
                })}
              </Badge>
            {/if}
          </div>
        </Card.Header>
        <Card.Content class="pt-0">
          {#if data.crawlerActiveInventoryLoadFailed}
            <Alert.Root variant="destructive">
              <TriangleAlert aria-hidden="true" />
              <Alert.Description>{m.crawler_active_inventory_load_error()}</Alert.Description>
            </Alert.Root>
          {:else if !data.crawlerActiveInventory || data.crawlerActiveInventory.items.length === 0}
            <p class="text-muted-foreground text-sm">
              {m.crawler_active_inventory_empty()}
            </p>
          {:else}
            <div class="overflow-x-auto">
              <Table.Root class="min-w-[56rem]">
                <Table.Caption class="sr-only">
                  {m.crawler_active_inventory_table_caption()}
                </Table.Caption>
                <Table.Header>
                  <Table.Row>
                    <Table.Head>{m.crawler_active_inventory_column_website()}</Table.Head>
                    <Table.Head>{m.crawler_active_inventory_column_status()}</Table.Head>
                    <Table.Head>{m.crawler_active_inventory_column_activity()}</Table.Head>
                    <Table.Head class="text-right">
                      {m.crawler_active_inventory_column_updated()}
                    </Table.Head>
                  </Table.Row>
                </Table.Header>
                <Table.Body>
                  {#each data.crawlerActiveInventory.items as activeItem (activeItem.job_id)}
                    <Table.Row>
                      <Table.Cell class="max-w-64">
                        <span
                          class="block truncate font-medium"
                          title={getCrawlerActiveInventoryWebsiteLabel(activeItem)}
                        >
                          {getCrawlerActiveInventoryWebsiteLabel(activeItem)}
                        </span>
                      </Table.Cell>
                      <Table.Cell>
                        <Badge
                          variant="outline"
                          class={activeStatusBadgeClass(activeItem.lifecycle_state)}
                        >
                          {getCrawlerActiveInventoryStatusLabel(activeItem)}
                        </Badge>
                      </Table.Cell>
                      <Table.Cell class="whitespace-normal">
                        <div class="flex flex-wrap gap-1.5">
                          {#each getCrawlerActiveInventoryResultLabels(activeItem) as label (label.label)}
                            <Badge
                              variant="outline"
                              class={resultBadgeClass(label.color)}
                              title={label.tooltip}
                            >
                              {label.label}
                            </Badge>
                          {/each}
                        </div>
                      </Table.Cell>
                      <Table.Cell class="text-muted-foreground text-right text-xs tabular-nums">
                        {formatDateTime(activeItem.job_updated_at)}
                      </Table.Cell>
                    </Table.Row>
                  {/each}
                </Table.Body>
              </Table.Root>
            </div>
          {/if}
        </Card.Content>
      </Card.Root>

      <Card.Root class="mb-14" aria-labelledby="crawler-recent-failures-title">
        <Card.Header>
          <div class="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
            <div class="flex min-w-0 flex-col gap-1">
              <h2 id="crawler-recent-failures-title" class="text-base leading-snug font-semibold">
                {m.crawler_recent_failures_title()}
              </h2>
              <Card.Description>
                {m.crawler_recent_failures_description({
                  days: data.crawlerRecentFailuresWindowDays
                })}
              </Card.Description>
            </div>
            {#if data.crawlerRecentFailures}
              <Badge variant="outline" class="shrink-0 tabular-nums">
                {m.crawler_recent_failures_count({
                  shown: data.crawlerRecentFailures.items.length,
                  total: data.crawlerRecentFailures.total
                })}
              </Badge>
            {/if}
          </div>
        </Card.Header>
        <Card.Content class="pt-0">
          {#if data.crawlerRecentFailuresLoadFailed}
            <Alert.Root variant="destructive">
              <TriangleAlert aria-hidden="true" />
              <Alert.Description>{m.crawler_recent_failures_load_error()}</Alert.Description>
            </Alert.Root>
          {:else if !data.crawlerRecentFailures || data.crawlerRecentFailures.items.length === 0}
            <p class="text-muted-foreground text-sm">
              {m.crawler_recent_failures_empty({
                days: data.crawlerRecentFailuresWindowDays
              })}
            </p>
          {:else}
            <div class="overflow-x-auto">
              <Table.Root class="min-w-[56rem]">
                <Table.Caption class="sr-only">
                  {m.crawler_recent_failures_table_caption()}
                </Table.Caption>
                <Table.Header>
                  <Table.Row>
                    <Table.Head>{m.crawler_recent_failures_column_website()}</Table.Head>
                    <Table.Head>{m.crawler_recent_failures_column_outcome()}</Table.Head>
                    <Table.Head>{m.crawler_recent_failures_column_activity()}</Table.Head>
                    <Table.Head class="text-right">
                      {m.crawler_recent_failures_column_finished()}
                    </Table.Head>
                  </Table.Row>
                </Table.Header>
                <Table.Body>
                  {#each data.crawlerRecentFailures.items as failure (failure.crawl_run_id)}
                    <Table.Row>
                      <Table.Cell class="max-w-64">
                        <span
                          class="block truncate font-medium"
                          title={getCrawlerRecentFailureWebsiteLabel(failure)}
                        >
                          {getCrawlerRecentFailureWebsiteLabel(failure)}
                        </span>
                      </Table.Cell>
                      <Table.Cell class="max-w-72 whitespace-normal">
                        <span class="text-sm">{getCrawlerRecentFailureOutcomeLabel(failure)}</span>
                      </Table.Cell>
                      <Table.Cell class="whitespace-normal">
                        <div class="flex flex-wrap gap-1.5">
                          {#each getCrawlerRecentFailureResultLabels(failure) as label (label.label)}
                            <Badge
                              variant="outline"
                              class={resultBadgeClass(label.color)}
                              title={label.tooltip}
                            >
                              {label.label}
                            </Badge>
                          {/each}
                        </div>
                      </Table.Cell>
                      <Table.Cell class="text-muted-foreground text-right text-xs tabular-nums">
                        {formatDateTime(failure.finished_at)}
                      </Table.Cell>
                    </Table.Row>
                  {/each}
                </Table.Body>
              </Table.Root>
            </div>
          {/if}
        </Card.Content>
      </Card.Root>

      <Settings.Group title={m.crawler_controls()}>
        <p class="text-secondary -mt-2 max-w-[64ch] pr-12 pl-2 text-sm leading-relaxed">
          {m.crawler_controls_subtitle()}
        </p>

        {#each CRAWLER_SETTINGS_BOOLEAN_FIELDS as field (field.key)}
          <Settings.Row
            title={fieldText(field.titleKey)}
            description={fieldText(field.descriptionKey)}
          >
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
          <Settings.Row
            title={fieldText(field.titleKey)}
            description={fieldText(field.descriptionKey)}
          >
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
                <div class="flex items-center gap-1.5">
                  {#if isDirty && !isSaving}
                    <Button variant="ghost" size="sm" onclick={() => resetField(field.key)}>
                      {m.reset()}
                    </Button>
                  {/if}
                  <Button
                    size="sm"
                    disabled={!isDirty || Boolean(error) || isSaving}
                    onclick={() => void handleSaveNumberSetting(field)}
                  >
                    {isSaving ? m.crawler_saving() : m.save()}
                  </Button>
                </div>
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
