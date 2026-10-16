<!--
  The attachments waiting in the composer. One or two are chips sharing a row;
  more fold into one summary row with the upload progress that unfolds on
  request, so a long list never pushes the composer down. The panel holds the
  full list once the message is sent.
-->
<script lang="ts">
  import { getAttachmentManager } from "$lib/features/attachments/AttachmentManager";
  import { Button } from "$lib/components/ui/button/index.js";
  import { X, LoaderCircle, Paperclip, ChevronDown, ChevronUp } from "@lucide/svelte";
  import { m } from "$lib/paraglide/messages";
  import { fileExtension } from "$lib/core/formatting/fileExtension";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import { pickFileIcon } from "$lib/core/formatting/pickFileIcon";
  import { get } from "svelte/store";
  import { getChatService } from "../../ChatService.svelte";

  const {
    state: { attachments, isUploading }
  } = getAttachmentManager();
  // Once a message is sent its attachments are shown in the pending message
  // bubble instead; the list comes back here if the send fails before the
  // backend accepts it.
  const chat = getChatService();

  // From this many attachments the list folds into a summary row. Two chips
  // split one row between them; a third would already stack.
  const SUMMARY_FROM = 3;
  let expanded = $state(false);

  const summary = $derived.by(() => {
    const list = $attachments;
    const done = list.filter((attachment) => attachment.status === "completed").length;
    const progress = list.reduce(
      (sum, attachment) => sum + (attachment.status === "completed" ? 100 : attachment.progress),
      0
    );
    return {
      count: list.length,
      bytes: list.reduce((sum, attachment) => sum + attachment.file.size, 0),
      done,
      percent: list.length === 0 ? 0 : Math.round(progress / list.length)
    };
  });
  const countLabel = $derived(
    summary.count === 1
      ? m.attachments_count_one({ count: summary.count })
      : m.attachments_count_other({ count: summary.count })
  );

  function removeAll() {
    // Snapshot first — each remove() mutates the store, so iterating the live
    // value can skip items.
    const snapshot = [...get(attachments)];
    snapshot.forEach((a) => a.remove());
  }
</script>

{#snippet chip(attachment: (typeof $attachments)[number])}
  {@const Icon = pickFileIcon(attachment.file.type)}
  {@const uploading = attachment.status !== "completed"}
  <div
    role="listitem"
    class="group border-default bg-primary hover:border-stronger relative flex h-8 max-w-full min-w-0 items-center gap-1.5 overflow-hidden rounded-lg border pr-1 pl-1.5 shadow-sm transition-colors"
    title={attachment.file.name}
  >
    <span
      class="bg-accent-dimmer text-accent-stronger flex size-5 flex-shrink-0 items-center justify-center rounded"
    >
      {#if uploading}
        <LoaderCircle class="size-3 animate-spin" aria-hidden="true" />
      {:else}
        <Icon class="size-3" aria-hidden="true" />
      {/if}
    </span>
    <span class="text-default min-w-0 flex-1 truncate text-xs">
      {attachment.file.name}
    </span>
    <span class="text-tertiary flex-shrink-0 text-[11px] tabular-nums">
      {#if uploading}
        {attachment.progress} %
      {:else}
        {fileExtension(attachment.file.name) || "FILE"} · {formatBytes(attachment.file.size)}
      {/if}
    </span>
    <Button
      type="button"
      variant="ghost"
      size="icon-xs"
      aria-label={m.remove_this_attachment()}
      onclick={() => attachment.remove()}
      class="text-tertiary hover:text-on-fill hover:bg-negative-default size-5 flex-shrink-0 rounded-full opacity-60 transition-all group-hover:opacity-100 focus-visible:opacity-100"
    >
      <X class="size-3" aria-hidden="true" />
    </Button>
    {#if uploading}
      <span
        class="bg-accent-default absolute inset-x-0 bottom-0 h-0.5 transition-[width]"
        style="width: {attachment.progress}%"
      ></span>
    {/if}
  </div>
{/snippet}

{#if $attachments && $attachments.length > 0 && !chat.askQuestion.isLoading}
  <div class="flex w-[100%] max-w-[74ch] flex-col gap-1.5 md:w-full">
    {#if summary.count >= SUMMARY_FROM}
      <div
        class="border-default bg-primary flex h-10 items-center gap-2 rounded-lg border px-2.5 shadow-sm"
      >
        <Paperclip class="text-tertiary size-3.5 flex-shrink-0" aria-hidden="true" />
        <span class="text-default flex-shrink-0 text-xs font-medium tabular-nums">{countLabel}</span
        >
        <span class="text-tertiary flex-shrink-0 text-xs tabular-nums">
          · {formatBytes(summary.bytes)}
        </span>
        {#if $isUploading}
          <span class="flex min-w-0 items-center gap-2">
            <span
              class="bg-secondary h-1 w-24 flex-shrink-0 overflow-hidden rounded-full"
              role="progressbar"
              aria-valuenow={summary.percent}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label={m.uploading()}
            >
              <span
                class="bg-accent-default block h-full transition-[width]"
                style="width: {summary.percent}%"
              ></span>
            </span>
            <span class="text-tertiary truncate text-xs tabular-nums">
              {m.attachments_pending_progress({ done: summary.done, total: summary.count })}
            </span>
          </span>
        {/if}
        <span class="flex-1"></span>
        <Button
          variant="ghost"
          size="xs"
          aria-expanded={expanded}
          onclick={() => (expanded = !expanded)}
          class="text-tertiary hover:text-default h-6 px-2 text-xs font-normal"
        >
          {expanded ? m.attachments_pending_hide() : m.attachments_pending_show()}
          {#if expanded}
            <ChevronUp class="size-3" aria-hidden="true" />
          {:else}
            <ChevronDown class="size-3" aria-hidden="true" />
          {/if}
        </Button>
        <Button
          variant="ghost"
          size="xs"
          onclick={removeAll}
          class="text-tertiary hover:text-default -mr-1 h-6 px-2 text-xs font-normal"
        >
          {m.remove_all_attachments()}
        </Button>
      </div>
      {#if expanded}
        <div
          class="attachments-scroll grid max-h-[146px] auto-rows-max grid-cols-1 gap-1.5 overflow-y-auto pr-0.5 sm:grid-cols-2"
          role="list"
          aria-label={countLabel}
        >
          {#each $attachments as attachment (attachment.id)}
            {@render chip(attachment)}
          {/each}
        </div>
      {/if}
    {:else}
      <div
        class="grid gap-1.5 {summary.count === 1
          ? 'grid-cols-1 justify-items-start'
          : 'grid-cols-1 sm:grid-cols-2'}"
        role="list"
        aria-label={countLabel}
      >
        {#each $attachments as attachment (attachment.id)}
          {@render chip(attachment)}
        {/each}
      </div>
    {/if}
  </div>
{/if}

<style>
  /* Subtle scrollbar — barely visible, full-color on hover.
     Matches the conversation's understated chrome instead of the system default. */
  .attachments-scroll {
    scrollbar-width: thin;
    scrollbar-color: transparent transparent;
    transition: scrollbar-color 150ms ease-out;
  }
  .attachments-scroll:hover {
    scrollbar-color: var(--border-stronger) transparent;
  }
  .attachments-scroll::-webkit-scrollbar {
    width: 6px;
  }
  .attachments-scroll::-webkit-scrollbar-track {
    background: transparent;
  }
  .attachments-scroll::-webkit-scrollbar-thumb {
    background: transparent;
    border-radius: 3px;
    transition: background 150ms ease-out;
  }
  .attachments-scroll:hover::-webkit-scrollbar-thumb {
    background: var(--border-stronger);
  }
</style>
