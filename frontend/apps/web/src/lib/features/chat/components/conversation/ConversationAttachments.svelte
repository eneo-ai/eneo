<script lang="ts">
  import { getAttachmentManager } from "$lib/features/attachments/AttachmentManager";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { X, Loader2, Paperclip } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import { formatFileType } from "$lib/core/formatting/formatFileType";
  import { pickFileIcon } from "$lib/core/formatting/pickFileIcon";
  import { get } from "svelte/store";

  const {
    state: { attachments }
  } = getAttachmentManager();

  function removeAll() {
    // Snapshot first — each remove() mutates the store, so iterating the live
    // value can skip items.
    const snapshot = [...get(attachments)];
    snapshot.forEach((a) => a.remove());
  }
</script>

{#if $attachments && $attachments.length > 0}
  <div class="flex w-[100%] max-w-[74ch] flex-col gap-2 md:w-full">
    {#if $attachments.length > 1}
      <div class="flex items-center justify-between px-0.5">
        <div class="text-secondary flex items-center gap-1.5 text-xs">
          <Paperclip class="size-3.5" aria-hidden="true" />
          <span class="tabular-nums">
            {m.attachments_count_other({ count: $attachments.length })}
          </span>
        </div>
        <Button
          variant="ghost"
          size="xs"
          onclick={removeAll}
          class="text-tertiary hover:text-default -mr-1.5 h-6 px-2 text-xs font-normal"
        >
          {m.remove_all_attachments()}
        </Button>
      </div>
    {/if}

    <div
      class="attachments-scroll grid max-h-[200px] auto-rows-max grid-cols-1 gap-2 overflow-y-auto pr-0.5 sm:grid-cols-2"
      role="list"
      aria-label={m.attachments_count_other({ count: $attachments.length })}
    >
      {#each $attachments as attachment (attachment.id)}
        {@const Icon = pickFileIcon(attachment.file.type)}
        {@const isUploading = attachment.status === "uploading" || attachment.status === "queued"}
        <Tooltip.Provider delayDuration={250}>
          <Tooltip.Root>
            <Tooltip.Trigger>
              {#snippet child({ props })}
                <div
                  {...props}
                  role="listitem"
                  class="group border-default bg-primary hover:border-stronger hover:bg-secondary relative flex h-11 min-w-0 items-center gap-2 rounded-lg border py-1.5 pr-2 pl-1.5 shadow-sm transition-all"
                >
                  <div
                    class="bg-accent-dimmer text-accent-stronger flex size-8 flex-shrink-0 items-center justify-center rounded-md"
                  >
                    {#if isUploading}
                      <Loader2 class="size-4 animate-spin" aria-hidden="true" />
                    {:else}
                      <Icon class="size-4" aria-hidden="true" />
                    {/if}
                  </div>

                  <div class="flex min-w-0 flex-1 flex-col leading-tight">
                    <span class="text-default truncate text-sm font-medium">
                      {attachment.file.name}
                    </span>
                    <span class="text-tertiary truncate text-[11px] tabular-nums">
                      {#if isUploading}
                        {attachment.progress}%
                      {:else}
                        {formatFileType(attachment.file.type) || "FILE"} · {formatBytes(
                          attachment.file.size
                        )}
                      {/if}
                    </span>
                  </div>

                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-xs"
                    aria-label={m.remove_this_attachment()}
                    onclick={(e) => {
                      e.stopPropagation();
                      attachment.remove();
                    }}
                    class="text-tertiary hover:text-on-fill hover:bg-negative-default size-5 flex-shrink-0 rounded-full opacity-60 transition-all group-hover:opacity-100"
                  >
                    <X class="size-3" aria-hidden="true" />
                  </Button>
                </div>
              {/snippet}
            </Tooltip.Trigger>
            <Tooltip.Content side="top" class="max-w-[320px]">
              <p class="break-all">{attachment.file.name}</p>
            </Tooltip.Content>
          </Tooltip.Root>
        </Tooltip.Provider>
      {/each}
    </div>
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
