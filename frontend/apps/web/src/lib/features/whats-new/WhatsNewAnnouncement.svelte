<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import * as Dialog from "$lib/components/ui/dialog";
  import { getAppContext } from "$lib/core/AppContext";
  import { m } from "$lib/paraglide/messages";
  import { getLocale, localizeHref } from "$lib/paraglide/runtime";
  import type { Localized, Release } from "@eneo/whats-new";
  import { announcementSummary } from "./announcement";
  import { labelFor, typeClass, typeLabel } from "./labels";
  import { getWhatsNewStore } from "./whatsNewStore";

  const { user } = getAppContext();
  const { pendingAnnouncement, markLatestAnnounced } = getWhatsNewStore();
  const locale = getLocale();

  let release = $state<Release | null>(null);
  let open = $state(false);

  const summary = $derived(
    release ? announcementSummary(release, user.hasPermission("admin")) : null
  );

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
    const { entries } = announcementSummary(pending, user.hasPermission("admin"));
    if (entries.length === 0) return;
    release = pending;
    open = true;
    void markLatestAnnounced();
  });

  function openWhatsNew() {
    open = false;
    // eslint-disable-next-line svelte/no-navigation-without-resolve -- localizeHref handles routing
    void goto(localizeHref("/whats-new"));
  }
</script>

{#if release && summary}
  <Dialog.Root bind:open>
    <Dialog.Content
      class="sm:max-w-xl"
      overlayClass="supports-backdrop-filter:backdrop-blur-md"
      closeLabel={m.close()}
    >
      <Dialog.Header>
        <Dialog.Title>{m.whats_new_announcement_title({ version: release.version })}</Dialog.Title>
        <Dialog.Description>{m.whats_new_announcement_intro()}</Dialog.Description>
      </Dialog.Header>

      <ul class="flex flex-col gap-4 py-2">
        {#each summary.entries as entry (entry.id)}
          <li class="flex flex-col gap-1">
            <div class="flex items-center gap-2">
              <Badge variant="outline" class="border-transparent {typeClass[entry.type] ?? ''}">
                {labelFor(typeLabel, entry.type)}
              </Badge>
              <span class="text-primary font-medium">{text(entry.title)}</span>
            </div>
            <p class="text-secondary text-sm leading-relaxed">{text(entry.body)}</p>
          </li>
        {/each}
      </ul>
      {#if summary.more > 0}
        <p class="text-muted text-sm">{m.whats_new_announcement_rest({ count: summary.more })}</p>
      {/if}

      <Dialog.Footer>
        <Button variant="outline" onclick={() => (open = false)}>
          {m.whats_new_announcement_later()}
        </Button>
        <Button onclick={openWhatsNew}>{m.whats_new_announcement_action()}</Button>
      </Dialog.Footer>
    </Dialog.Content>
  </Dialog.Root>
{/if}
