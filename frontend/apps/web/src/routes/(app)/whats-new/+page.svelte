<script lang="ts">
  import { onMount } from "svelte";
  import { toastError } from "$lib/core/errors";
  import { Page } from "$lib/components/layout";
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import { getAppContext } from "$lib/core/AppContext";
  import { getWhatsNewStore } from "$lib/features/whats-new/whatsNewStore";
  import { showMe } from "$lib/features/whats-new/spotlight";
  import { startTour, tourSteps } from "$lib/features/whats-new/tour";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import { Label } from "$lib/components/ui/label";
  import { Switch } from "$lib/components/ui/switch";
  import { areaLabel, labelFor, typeClass, typeLabel } from "$lib/features/whats-new/labels";
  import {
    areasPresent,
    countEntries,
    filterEntries,
    isReadRelease,
    type WhatsNewFilters
  } from "$lib/features/whats-new/filters";
  import { releases } from "@eneo/whats-new";
  import type { EntryArea, Localized, Release, ReleaseEntry } from "@eneo/whats-new";
  import { Sparkles } from "lucide-svelte";
  import { get } from "svelte/store";

  const { user, settings } = getAppContext();
  const { markLatestSeen, seenVersion, resetState } = getWhatsNewStore();
  const developerTools = settings.developer_tools_available === true;
  const isAdmin = user.hasPermission("admin");
  const locale = getLocale();

  // Snapshot before this visit marks the newest release as seen, so "read"
  // means read before today, not "read because the page just opened".
  const seenAtOpen = get(seenVersion);

  // One release at a time, newest by default; older ones via the picker.
  let selectedVersion = $state<string | null>(releases[0]?.version ?? null);
  const current = $derived(releases.find((r) => r.version === selectedVersion) ?? null);
  const currentRead = $derived(current ? isReadRelease(current, seenAtOpen) : false);
  const areas = $derived(current ? areasPresent([current], isAdmin) : []);
  const total = $derived(current ? countEntries([current], isAdmin) : 0);

  let filters = $state<WhatsNewFilters>({ area: null, showMeOnly: false });
  const entries = $derived(current ? filterEntries(current, filters, isAdmin) : []);

  function selectRelease(version: string) {
    selectedVersion = version;
    // An area from the previous release may not exist in this one.
    if (
      filters.area &&
      !areasPresent([releases.find((r) => r.version === version)!], isAdmin).includes(filters.area)
    ) {
      filters.area = null;
    }
  }

  function selectArea(area: EntryArea | null) {
    filters.area = area;
  }

  function clearFilters() {
    filters = { area: null, showMeOnly: false };
  }

  function text(value: Localized): string {
    return value[locale] ?? value.en;
  }

  function formatDate(date: string): string {
    return new Intl.DateTimeFormat(locale, { dateStyle: "long" }).format(new Date(date));
  }

  // Both navigate away; when an anchor is missing on its page the user
  // still lands on the right screen, which is the documented fallback.
  function handleShowMe(entry: ReleaseEntry) {
    if (!entry.showMe) return;
    void showMe(
      { ...entry.showMe, title: text(entry.title), description: text(entry.body) },
      { done: m.whats_new_spotlight_done() }
    );
  }

  function handleTour(release: Release) {
    void startTour(tourSteps(release, isAdmin, locale), {
      done: m.whats_new_spotlight_done(),
      next: m.whats_new_tour_next(),
      previous: m.whats_new_tour_previous(),
      progress: m.whats_new_tour_progress({ current: "{{current}}", total: "{{total}}" })
    });
  }

  function tourLength(release: Release): number {
    return tourSteps(release, isAdmin, locale).length;
  }

  let resetting = $state(false);

  // The announcement runs on app load, so a full reload is what brings it
  // back after the markers are forgotten.
  async function resetAndReload() {
    resetting = true;
    try {
      await resetState();
      window.location.reload();
    } catch (error) {
      resetting = false;
      toastError(error, m.whats_new_dev_reset_failed());
    }
  }

  onMount(() => {
    void markLatestSeen();
  });
</script>

<svelte:head>
  <title>{m.app_name()} – {m.whats_new()}</title>
</svelte:head>

<!-- The (app) shell positions <main> relatively; pages without a sidebar layout
     stretch themselves like account/admin do. -->
<div class="absolute inset-0 flex">
  <Page.Root>
    <Page.Header>
      <Page.Title title={m.whats_new()}></Page.Title>
    </Page.Header>
    <Page.Main>
      <div class="flex max-w-3xl flex-col gap-10 py-6 pr-6">
        <p class="text-secondary">{m.whats_new_intro()}</p>

        {#if releases.length === 0}
          <div class="text-muted flex items-center gap-2">
            <Sparkles class="size-4" aria-hidden="true" />
            {m.whats_new_empty()}
          </div>
        {:else if current}
          <div class="flex flex-col gap-3">
            <span id="whats-new-release-picker" class="text-secondary text-sm font-medium">
              {m.whats_new_release_picker()}
            </span>
            <div
              role="group"
              aria-labelledby="whats-new-release-picker"
              class="flex flex-wrap items-center gap-2"
            >
              {#each releases as release (release.version)}
                <button
                  type="button"
                  aria-pressed={release.version === selectedVersion}
                  onclick={() => selectRelease(release.version)}
                  class="border-default text-secondary hover:bg-hover-dimmer aria-pressed:bg-accent-default aria-pressed:text-on-fill aria-pressed:border-transparent inline-flex h-9 items-center gap-2 rounded-lg border px-3 text-sm font-medium transition-colors"
                >
                  {release.version}
                  {#if !release.date}
                    <span class="text-xs opacity-80">{m.whats_new_upcoming()}</span>
                  {/if}
                  {#if seenAtOpen !== null && !isReadRelease(release, seenAtOpen)}
                    <span class="bg-positive-default size-2 rounded-full" aria-hidden="true"></span>
                    <span class="sr-only">{m.whats_new_new_for_you()}</span>
                  {/if}
                </button>
              {/each}
            </div>
          </div>

          <section aria-labelledby="release-{current.version}" class="flex flex-col gap-5">
            <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <h2 id="release-{current.version}" class="text-primary text-xl font-semibold">
                {m.whats_new_release({ version: current.version })}
              </h2>
              <span class="text-muted text-sm">
                {#if current.date}
                  {formatDate(current.date)}
                {:else}
                  {m.whats_new_upcoming()}
                {/if}
              </span>
              {#if seenAtOpen !== null}
                {#if currentRead}
                  <span class="text-muted text-xs">{m.whats_new_read()}</span>
                {:else}
                  <Badge
                    variant="outline"
                    class="bg-positive-default/10 text-positive-stronger border-transparent"
                  >
                    {m.whats_new_new_for_you()}
                  </Badge>
                {/if}
              {/if}
              {#if tourLength(current) > 0}
                <Button
                  variant={currentRead ? "outline" : "default"}
                  size="sm"
                  class="ml-auto"
                  onclick={() => handleTour(current)}
                >
                  {m.whats_new_tour_start({ count: tourLength(current) })}
                </Button>
              {/if}
            </div>

            {#if total > 0}
              <div
                role="group"
                aria-label={m.whats_new_filters_label()}
                class="border-default flex flex-col gap-3 border-b pb-4"
              >
                <div class="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    aria-pressed={filters.area === null}
                    onclick={() => selectArea(null)}
                    class="border-default text-secondary hover:bg-hover-dimmer aria-pressed:bg-accent-default aria-pressed:text-on-fill aria-pressed:border-transparent h-7 rounded-full border px-3 text-[0.8rem] font-medium transition-colors"
                  >
                    {m.whats_new_filter_all()}
                  </button>
                  {#each areas as area (area)}
                    <button
                      type="button"
                      aria-pressed={filters.area === area}
                      onclick={() => selectArea(area)}
                      class="border-default text-secondary hover:bg-hover-dimmer aria-pressed:bg-accent-default aria-pressed:text-on-fill aria-pressed:border-transparent h-7 rounded-full border px-3 text-[0.8rem] font-medium transition-colors"
                    >
                      {labelFor(areaLabel, area)}
                    </button>
                  {/each}
                </div>
                <div class="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
                  <div class="flex items-center gap-2">
                    <Switch id="whats-new-show-me" size="sm" bind:checked={filters.showMeOnly} />
                    <Label for="whats-new-show-me" class="font-normal">
                      {m.whats_new_filter_show_me()}
                    </Label>
                  </div>
                  <span class="text-muted ml-auto text-xs" aria-live="polite">
                    {m.whats_new_count({ shown: entries.length, total })}
                  </span>
                </div>
              </div>
            {/if}

            {#if total === 0}
              <div class="text-muted flex items-center gap-2">
                <Sparkles class="size-4" aria-hidden="true" />
                {m.whats_new_empty()}
              </div>
            {:else if entries.length === 0}
              <div class="text-muted flex flex-wrap items-center gap-3">
                <span>{m.whats_new_no_match()}</span>
                <Button variant="outline" size="sm" onclick={clearFilters}>
                  {m.whats_new_clear_filters()}
                </Button>
              </div>
            {/if}

            <ul class="flex flex-col gap-4">
              {#each entries as entry (entry.id)}
                <li
                  id={entry.id}
                  class="border-default bg-primary flex flex-col gap-2 rounded-lg border p-4"
                >
                  <div class="flex flex-wrap items-center gap-2 text-xs">
                    <Badge
                      variant="outline"
                      class="border-transparent {typeClass[entry.type] ?? ''}"
                    >
                      {labelFor(typeLabel, entry.type)}
                    </Badge>
                    <span class="text-muted">{labelFor(areaLabel, entry.area)}</span>
                    {#if entry.audience === "admin"}
                      <span class="text-muted" aria-hidden="true">·</span>
                      <span class="text-muted">{m.whats_new_admin_only()}</span>
                    {/if}
                  </div>
                  <h3 class="text-primary font-medium">{text(entry.title)}</h3>
                  <p class="text-secondary text-sm leading-relaxed">{text(entry.body)}</p>
                  {#if entry.showMe}
                    <div class="pt-1">
                      <Button variant="outline" size="sm" onclick={() => handleShowMe(entry)}>
                        {m.whats_new_show_me()}
                      </Button>
                    </div>
                  {/if}
                </li>
              {/each}
            </ul>
          </section>
        {/if}

        {#if developerTools}
          <div
            class="border-warning-default/40 bg-warning-default/5 flex flex-wrap items-center justify-between gap-3 rounded-lg border p-4"
          >
            <div class="flex flex-col gap-0.5">
              <span class="text-primary text-sm font-medium">{m.whats_new_dev_title()}</span>
              <span class="text-secondary text-xs">{m.whats_new_dev_description()}</span>
            </div>
            <Button variant="outline" size="sm" disabled={resetting} onclick={resetAndReload}>
              {m.whats_new_dev_reset()}
            </Button>
          </div>
        {/if}

        <p class="text-muted text-sm">
          <a
            href="https://docs.eneo.ai/about/release-notes"
            target="_blank"
            rel="noreferrer"
            class="hover:text-primary underline underline-offset-2"
          >
            {m.whats_new_docs_link()}
          </a>
        </p>
      </div>
    </Page.Main>
  </Page.Root>
</div>
