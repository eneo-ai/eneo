<script lang="ts">
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import type { AttachmentValidationError } from "$lib/features/attachments/AttachmentManager";
  import { m } from "$lib/paraglide/messages";

  export let errors: AttachmentValidationError[] = [];

  const isFileSizeError = (
    error: AttachmentValidationError
  ): error is AttachmentValidationError & {
    fileName: string;
    fileSizeBytes: number;
    maxSizeBytes: number;
  } => {
    return (
      error.kind === "file_size" &&
      typeof error.fileName === "string" &&
      typeof error.fileSizeBytes === "number" &&
      typeof error.maxSizeBytes === "number"
    );
  };

  $: fileSizeErrors = errors.filter(isFileSizeError);
  $: otherErrors = errors.filter((error) => error.kind !== "file_size").map((error) => error.message);
</script>

{#if errors.length > 0}
  <div class="bg-negative-dimmer text-negative-default mt-3 rounded-md px-3 py-2 text-sm">
    <ul class="list-disc space-y-1 pl-4">
      {#each fileSizeErrors as error}
        <li>
          {m.file_too_large_detail({
            fileName: error.fileName,
            currentSize: formatBytes(error.fileSizeBytes),
            maxSize: formatBytes(error.maxSizeBytes)
          })}
        </li>
      {/each}

      {#each otherErrors as error}
        <li>{error}</li>
      {/each}
    </ul>
  </div>
{/if}
