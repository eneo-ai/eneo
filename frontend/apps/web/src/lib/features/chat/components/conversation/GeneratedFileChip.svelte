<script lang="ts">
  import { Download } from "@lucide/svelte";
  import { sanitizeLinkHref } from "$lib/components/markdown/index.js";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import { pickFileIcon } from "$lib/core/formatting/pickFileIcon";
  import { getFilePreview } from "$lib/features/file-preview/FilePreview.svelte";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    file: {
      id: string;
      name: string;
      mimetype: string;
      size: number;
      original_size?: number | null;
    };
    /** Signed download URL; null while it is being minted. */
    url: string | null;
  };

  const { file, url }: Props = $props();
  const preview = getFilePreview();
  const href = $derived(sanitizeLinkHref(url));
  const Icon = $derived(pickFileIcon(file.mimetype));
  // The downloaded file's size; `size` counts the extracted text of a document.
  const bytes = $derived(file.original_size ?? file.size);
  const extension = $derived(
    file.name.includes(".") ? (file.name.split(".").pop() ?? "").toUpperCase() : ""
  );
  const previewable = $derived(preview?.canPreview(file) ?? false);
  const previewing = $derived(preview?.isOpen(file) ?? false);
</script>

{#snippet description()}
  <span
    class="bg-accent-dimmer text-accent-stronger flex size-8 flex-shrink-0 items-center justify-center rounded-md"
  >
    <Icon class="size-4" aria-hidden="true" />
  </span>
  <span class="flex min-w-0 flex-1 flex-col leading-tight">
    <span class="text-default truncate text-sm font-medium">{file.name}</span>
    <span class="text-tertiary truncate text-[11px] tabular-nums">
      {extension}{bytes > 0 ? ` · ${formatBytes(bytes)}` : ""}
    </span>
  </span>
{/snippet}

<!-- A document a tool created in this answer. -->
<!-- eslint-disable svelte/no-navigation-without-resolve -- signed file URL -->
{#if previewable}
  <!-- The chip opens the document beside the conversation; downloading is its
       own action at the end of the chip. -->
  <div
    title={file.name}
    class="bg-primary mt-2 flex h-11 w-full max-w-[21rem] min-w-0 items-stretch rounded-lg border shadow-sm transition-colors {previewing
      ? 'border-accent-default'
      : 'border-default hover:border-stronger'}"
  >
    <button
      type="button"
      aria-label={m.file_preview_open({ name: file.name })}
      aria-expanded={previewing}
      onclick={(event) => preview?.toggle(file, event.currentTarget)}
      class="hover:bg-secondary focus-visible:ring-accent-default flex min-w-0 flex-1 items-center gap-2 rounded-l-[inherit] py-1.5 pr-2 pl-1.5 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none"
    >
      {@render description()}
    </button>
    <a
      href={href ?? undefined}
      download={file.name}
      aria-label={m.generated_file_download({ name: file.name })}
      aria-disabled={href ? undefined : "true"}
      title={m.download()}
      class="border-default text-secondary hover:bg-secondary hover:text-default focus-visible:ring-accent-default flex w-10 flex-shrink-0 items-center justify-center rounded-r-[inherit] border-l transition-colors focus-visible:ring-2 focus-visible:outline-none {href
        ? ''
        : 'pointer-events-none opacity-60'}"
    >
      <Download class="size-4" aria-hidden="true" />
    </a>
  </div>
{:else}
  <!-- Nothing to preview (or no panel to preview in): the chip is the download. -->
  <a
    href={href ?? undefined}
    download={file.name}
    aria-label={m.generated_file_download({ name: file.name })}
    aria-disabled={href ? undefined : "true"}
    title={file.name}
    class="group border-default bg-primary hover:bg-secondary hover:border-stronger focus-visible:ring-accent-default mt-2 flex h-11 w-full max-w-[21rem] min-w-0 items-center gap-2 rounded-lg border py-1.5 pr-2 pl-1.5 no-underline shadow-sm transition-colors focus-visible:ring-2 focus-visible:outline-none {href
      ? ''
      : 'pointer-events-none opacity-60'}"
  >
    {@render description()}
    <Download
      class="text-secondary group-hover:text-default size-4 flex-shrink-0"
      aria-hidden="true"
    />
  </a>
{/if}
<!-- eslint-enable svelte/no-navigation-without-resolve -->
