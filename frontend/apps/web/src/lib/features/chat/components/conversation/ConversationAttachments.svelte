<script lang="ts">
  import { IconDocument } from "@intric/icons/document";
  import { IconXMark } from "@intric/icons/x-mark";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { getAttachmentManager } from "$lib/features/attachments/AttachmentManager";
  import { Button, Tooltip } from "@intric/ui";

  const {
    state: { attachments }
  } = getAttachmentManager();
  import { m } from "$lib/paraglide/messages";
</script>

{#if $attachments && $attachments.length > 0}
  <div class="flex w-full max-w-[74ch] flex-wrap gap-2">
    {#each $attachments as attachment (attachment.id)}
      <div
        class="group border-stronger bg-primary hover:bg-secondary relative flex items-center gap-3.5 rounded-xl border py-1.5 pr-6 pl-1.5 shadow-md"
      >
        <div
          class="flex h-11 w-11 items-center justify-center rounded-lg {attachment.status ===
          'uploading'
            ? 'bg-secondary'
            : 'bg-accent-default'}"
        >
          <div class="relative flex h-full w-full items-center justify-center">
            {#if attachment.status === "uploading"}
              <IconLoadingSpinner class="animate-spin" />
            {:else}
              <IconDocument class="stroke-white" />
            {/if}
          </div>
        </div>

        <div class="flex flex-col">
          <div>
            {attachment.file.name}
          </div>
          <div class="text-secondary text-sm">
            {attachment.file.type
              .split("/")
              [attachment.file.type.split("/").length - 1].toUpperCase()}
          </div>
        </div>

        <Tooltip text={m.remove_attachment()} asFragment let:trigger>
          <Button
            unstyled
            aria-label={m.remove_this_attachment()}
            is={trigger}
            on:click={() => attachment.remove()}
            class="border-stronger bg-primary text-primary hover:bg-negative-default hover:text-on-fill absolute -top-2.5 -right-2 flex h-6 w-6 items-center justify-center rounded-full border p-0.5 group-hover:opacity-100 focus-within:opacity-100 lg:opacity-0"
          >
            <IconXMark />
          </Button>
        </Tooltip>
      </div>
    {/each}
  </div>
{/if}
