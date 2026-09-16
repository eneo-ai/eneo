<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import EneoWordMark from "$lib/assets/EneoWordMark.svelte";
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import * as Dialog from "$lib/components/ui/dialog";
  import { getAppContext } from "$lib/core/AppContext";
  import { m } from "$lib/paraglide/messages";
  import { getLocale, localizeHref } from "$lib/paraglide/runtime";
  import type { Localized, Release } from "@eneo/whats-new";
  import { ArrowRight } from "lucide-svelte";
  import { announcementSummary } from "./announcement";
  import { areaIcon, labelFor, typeClass, typeLabel } from "./labels";
  import { startTour, tourSteps } from "./tour";
  import { getWhatsNewStore } from "./whatsNewStore";

  const { user } = getAppContext();
  const { pendingAnnouncement, markLatestAnnounced } = getWhatsNewStore();
  const locale = getLocale();
  const isAdmin = user.hasPermission("admin");

  let release = $state<Release | null>(null);
  let open = $state(false);

  const summary = $derived(release ? announcementSummary(release, isAdmin) : null);
  const steps = $derived(release ? tourSteps(release, isAdmin, locale) : []);

  function text(value: Localized): string {
    return value[locale] ?? value.en;
  }

  // Shown once per user and release, on the first app load after the
  // release reaches them. Recorded as announced when opened, so a reload
  // without dismissing does not repeat it; closing is not "seen" — the
  // menu dot stays until they open the page.
  onMount(() => {
    const pending = pendingAnnouncement();
    if (!pending) return;
    if (announcementSummary(pending, isAdmin).entries.length === 0) return;
    release = pending;
    open = true;
    void markLatestAnnounced();
  });

  function openWhatsNew() {
    open = false;
    // eslint-disable-next-line svelte/no-navigation-without-resolve -- localizeHref handles routing
    void goto(localizeHref("/whats-new"));
  }

  // The primary action walks through the release's Show me stops; a release
  // without any falls back to the page.
  function primary() {
    if (steps.length === 0) return openWhatsNew();
    open = false;
    void startTour(steps, {
      done: m.whats_new_spotlight_done(),
      next: m.whats_new_tour_next(),
      previous: m.whats_new_tour_previous(),
      progress: m.whats_new_tour_progress({ current: "{{current}}", total: "{{total}}" })
    });
  }
</script>

{#if release && summary}
  <Dialog.Root bind:open>
    <Dialog.Content
      class="max-h-[calc(100dvh-2rem)] gap-0 overflow-y-auto p-0 sm:max-w-3xl"
      overlayClass="supports-backdrop-filter:backdrop-blur-md"
      closeLabel={m.close()}
    >
      <div class="grid md:min-h-[520px] md:grid-cols-[280px_minmax(0,1fr)]">
        <!-- Brand panel: bg-foreground/text-background invert with the theme, so
             it stays a high-contrast panel in both light and dark mode. -->
        <div class="bg-foreground text-background flex flex-col gap-6 p-7">
          <EneoWordMark class="h-7 w-auto" aria-hidden="true" />
          <Dialog.Header class="gap-2 text-left">
            <span class="text-background/75 text-xs font-semibold tracking-[0.08em] uppercase">
              {m.whats_new_release({ version: release.version })}
            </span>
            <Dialog.Title class="text-background text-2xl leading-tight font-bold tracking-tight">
              {m.whats_new_announcement_heading()}
            </Dialog.Title>
            <Dialog.Description class="text-background/85 text-sm leading-relaxed">
              {m.whats_new_announcement_intro_count({ count: summary.total })}
            </Dialog.Description>
          </Dialog.Header>
          <div class="mt-auto flex flex-col gap-2 pt-4">
            <Button
              size="lg"
              class="bg-background text-foreground hover:bg-background/90 focus-visible:ring-background/60 h-11 w-full justify-center"
              onclick={primary}
            >
              {steps.length > 0
                ? m.whats_new_announcement_tour()
                : m.whats_new_announcement_action()}
              <ArrowRight data-icon="inline-end" aria-hidden="true" />
            </Button>
            <Button
              variant="ghost"
              size="lg"
              class="text-background hover:bg-background/10 hover:text-background focus-visible:ring-background/60 h-11 w-full justify-center"
              onclick={() => (open = false)}
            >
              {m.whats_new_announcement_later()}
            </Button>
          </div>
        </div>

        <!-- pt-12 keeps the close button's row clear of the first cards. -->
        <div class="flex flex-col gap-4 px-6 pt-12 pb-6">
          <ul class="grid gap-3 sm:grid-cols-2" aria-label={m.whats_new_announcement_list_label()}>
            {#each summary.entries as entry (entry.id)}
              {@const Icon = areaIcon[entry.area]}
              <li class="border-default flex flex-col gap-2 rounded-lg border p-4">
                <div class="flex items-center justify-between gap-2">
                  <span
                    class="bg-accent-dimmer text-accent-stronger flex size-8 shrink-0 items-center justify-center rounded-md"
                    aria-hidden="true"
                  >
                    {#if Icon}<Icon class="size-4" />{/if}
                  </span>
                  <Badge variant="outline" class="border-transparent {typeClass[entry.type] ?? ''}">
                    {labelFor(typeLabel, entry.type)}
                  </Badge>
                </div>
                <h3 class="text-primary text-sm leading-snug font-semibold">{text(entry.title)}</h3>
                <p class="text-secondary line-clamp-4 text-xs leading-relaxed">
                  {text(entry.body)}
                </p>
              </li>
            {/each}
          </ul>
          <Button
            variant="link"
            class="text-accent-stronger hover:text-accent-default h-9 w-fit gap-1.5 px-1 text-sm font-medium"
            onclick={openWhatsNew}
          >
            {m.whats_new_announcement_all({ count: summary.total })}
            <ArrowRight class="size-3.5" aria-hidden="true" />
          </Button>
        </div>
      </div>
    </Dialog.Content>
  </Dialog.Root>
{/if}
