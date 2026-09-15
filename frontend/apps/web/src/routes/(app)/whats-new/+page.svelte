<script lang="ts">
  import { onMount } from "svelte";
  import { Page } from "$lib/components/layout";
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import { getAppContext } from "$lib/core/AppContext";
  import { getWhatsNewStore } from "$lib/features/whats-new/whatsNewStore";
  import { showMe } from "$lib/features/whats-new/spotlight";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import { areaLabel, labelFor, typeClass, typeLabel } from "$lib/features/whats-new/labels";
  import { releases, visibleEntries } from "@eneo/whats-new";
  import type { Localized, ReleaseEntry } from "@eneo/whats-new";
  import { Sparkles } from "lucide-svelte";

  const { user } = getAppContext();
  const { markLatestSeen } = getWhatsNewStore();
  const isAdmin = user.hasPermission("admin");
  const locale = getLocale();

  function text(value: Localized): string {
    return value[locale] ?? value.en;
  }

  function formatDate(date: string): string {
    return new Intl.DateTimeFormat(locale, { dateStyle: "long" }).format(new Date(date));
  }

  // Navigates away; when the anchor is missing on the target page the user
  // still lands on the right screen, which is the documented fallback.
  function handleShowMe(entry: ReleaseEntry) {
    if (!entry.showMe) return;
    void showMe(entry.showMe, {
      title: text(entry.title),
      description: text(entry.body),
      doneLabel: m.whats_new_spotlight_done()
    });
  }

  const visibleReleases = $derived(
    releases
      .map((release) => ({ ...release, entries: visibleEntries(release, isAdmin) }))
      .filter((release) => release.entries.length > 0)
  );

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

        {#if visibleReleases.length === 0}
          <div class="text-muted flex items-center gap-2">
            <Sparkles class="size-4" aria-hidden="true" />
            {m.whats_new_empty()}
          </div>
        {/if}

        {#each visibleReleases as release (release.version)}
          <section aria-labelledby="release-{release.version}" class="flex flex-col gap-5">
            <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <h2 id="release-{release.version}" class="text-primary text-xl font-semibold">
                {m.whats_new_release({ version: release.version })}
              </h2>
              <span class="text-muted text-sm">
                {#if release.date}
                  {formatDate(release.date)}
                {:else}
                  {m.whats_new_upcoming()}
                {/if}
              </span>
            </div>

            <ul class="flex flex-col gap-4">
              {#each release.entries as entry (entry.id)}
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
        {/each}

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
