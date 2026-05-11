<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { invalidate } from "$app/navigation";
  import { Page, Settings } from "$lib/components/layout";
  import { toast } from "$lib/components/toast";
  import { getIntric } from "$lib/core/Intric.js";
  import { toastError } from "$lib/core/errors";
  import {
    CRAWLER_SETTINGS_EDITABLE_FIELDS,
    CRAWLER_SETTINGS_READ_ONLY_OPTIMIZATIONS,
    type CrawlerSettingsEditableKey
  } from "$lib/features/admin/crawlerSettings";
  import { m } from "$lib/paraglide/messages";
  import { Input } from "@intric/ui";
  import { Gauge } from "lucide-svelte";

  const intric = getIntric();
  let { data } = $props();

  let crawlSitemapLastmodSkipEnabled = $state(false);
  let obeyRobots = $state(false);
  let autothrottleEnabled = $state(false);

  $effect.pre(() => {
    const crawlerSettings = data.crawlerSettings;
    crawlSitemapLastmodSkipEnabled = crawlerSettings.settings.crawl_sitemap_lastmod_skip_enabled;
    obeyRobots = crawlerSettings.settings.obey_robots;
    autothrottleEnabled = crawlerSettings.settings.autothrottle_enabled;
  });

  function getFieldValue(key: CrawlerSettingsEditableKey): boolean {
    if (key === "crawl_sitemap_lastmod_skip_enabled") {
      return crawlSitemapLastmodSkipEnabled;
    }
    if (key === "obey_robots") {
      return obeyRobots;
    }
    return autothrottleEnabled;
  }

  function setFieldValue(key: CrawlerSettingsEditableKey, value: boolean) {
    if (key === "crawl_sitemap_lastmod_skip_enabled") {
      crawlSitemapLastmodSkipEnabled = value;
      return;
    }
    if (key === "obey_robots") {
      obeyRobots = value;
      return;
    }
    autothrottleEnabled = value;
  }

  async function handleToggleCrawlerSetting(
    key: CrawlerSettingsEditableKey,
    { current, next }: { current: boolean; next: boolean }
  ) {
    setFieldValue(key, next);

    try {
      const updatedSettings = await intric.settings.updateCrawler({ [key]: next });
      crawlSitemapLastmodSkipEnabled = updatedSettings.settings.crawl_sitemap_lastmod_skip_enabled;
      obeyRobots = updatedSettings.settings.obey_robots;
      autothrottleEnabled = updatedSettings.settings.autothrottle_enabled;
      await invalidate("admin:crawler-settings");
      toast.success(m.crawler_settings_saved());
    } catch (error) {
      setFieldValue(key, current);
      toastError(error, m.could_not_update_crawler_settings());
    }
  }

  function fieldText(key: string) {
    switch (key) {
      case "crawler_hash_skip_title":
        return m.crawler_hash_skip_title();
      case "crawler_hash_skip_description":
        return m.crawler_hash_skip_description();
      case "crawler_lastmod_skip_title":
        return m.crawler_lastmod_skip_title();
      case "crawler_lastmod_skip_description":
        return m.crawler_lastmod_skip_description();
      case "crawler_lastmod_skip_warning":
        return m.crawler_lastmod_skip_warning();
      case "crawler_obey_robots_title":
        return m.crawler_obey_robots_title();
      case "crawler_obey_robots_description":
        return m.crawler_obey_robots_description();
      case "crawler_autothrottle_title":
        return m.crawler_autothrottle_title();
      case "crawler_autothrottle_description":
        return m.crawler_autothrottle_description();
      default:
        return key;
    }
  }

  function fieldDescription(field: { descriptionKey: string; warningKey?: string }) {
    const description = fieldText(field.descriptionKey);
    return field.warningKey ? `${description}\n${fieldText(field.warningKey)}` : description;
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
        {#each CRAWLER_SETTINGS_EDITABLE_FIELDS as field (field.key)}
          <Settings.Row title={fieldText(field.titleKey)} description={fieldDescription(field)}>
            <Input.Switch
              value={getFieldValue(field.key)}
              sideEffect={(change) => handleToggleCrawlerSetting(field.key, change)}
            />
          </Settings.Row>
        {/each}
      </Settings.Group>
    </Settings.Page>
  </Page.Main>
</Page.Root>
