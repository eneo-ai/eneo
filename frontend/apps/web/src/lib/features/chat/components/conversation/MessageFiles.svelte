<script lang="ts">
  import { IconAttachment } from "@eneo/icons/attachment";
  import { getMessageContext } from "../../MessageContext.svelte";
  import { getAttachmentUrlService } from "$lib/features/attachments/AttachmentUrlService.svelte";
  import AsyncImage from "$lib/components/AsyncImage.svelte";

  const attachmentUrlService = getAttachmentUrlService();
  const { current } = getMessageContext();

  const files = $derived.by(() =>
    current().files.map((file) => {
      const extension = file.name.split(".")[file.name.split(".").length - 1].toUpperCase();

      if (file.mimetype.includes("image")) {
        return {
          id: file.id,
          name: file.name,
          type: "image",
          url: attachmentUrlService.getUrl(file) ?? null,
          extension
        };
      }

      return {
        id: file.id,
        name: file.name,
        type: "generic",
        extension,
        url: null
      };
    })
  );
</script>

{#if files.length > 0}
  <div class="flex w-full flex-wrap items-center justify-end gap-2">
    {#each files as file (file.id)}
      {#if file.type === "image"}
        <div class="ml-12 overflow-clip rounded-lg border shadow-md">
          <AsyncImage url={file.url} fixedAspectRatio={false}></AsyncImage>
        </div>
      {:else}
        <div
          class="group border-default hover:bg-hover-dimmer flex items-center gap-3.5 rounded-md border py-1.5 pr-6 pl-1.5"
        >
          <div
            class="bg-accent-default flex min-h-12 min-w-12 items-center justify-center rounded-md"
          >
            <IconAttachment class="text-on-fill" />
          </div>
          <div>
            <p class="line-clamp-1 group-hover:line-clamp-none">
              {file.name}
            </p>
            <p class="text-secondary text-sm">
              {file.extension}
            </p>
          </div>
        </div>
      {/if}
    {/each}
  </div>
{/if}
