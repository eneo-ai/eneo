<script lang="ts">
  import { Download } from "@lucide/svelte";
  import { sanitizeLinkHref } from "$lib/components/markdown/index.js";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import { pickFileIcon } from "$lib/core/formatting/pickFileIcon";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    file: { name: string; mimetype: string; size: number };
    /** Signed download URL; null while it is being minted. */
    url: string | null;
  };

  const { file, url }: Props = $props();
  const href = $derived(sanitizeLinkHref(url));
  const Icon = $derived(pickFileIcon(file.mimetype));
  const extension = $derived(
    file.name.includes(".") ? (file.name.split(".").pop() ?? "").toUpperCase() : ""
  );
</script>

<!-- A document a tool created in this answer, offered as a download. -->
<!-- eslint-disable svelte/no-navigation-without-resolve -- signed file URL -->
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
  <span
    class="bg-accent-dimmer text-accent-stronger flex size-8 flex-shrink-0 items-center justify-center rounded-md"
  >
    <Icon class="size-4" aria-hidden="true" />
  </span>
  <span class="flex min-w-0 flex-1 flex-col leading-tight">
    <span class="text-default truncate text-sm font-medium">{file.name}</span>
    <span class="text-tertiary truncate text-[11px] tabular-nums">
      {extension}{file.size > 0 ? ` · ${formatBytes(file.size)}` : ""}
    </span>
  </span>
  <Download
    class="text-secondary group-hover:text-default size-4 flex-shrink-0"
    aria-hidden="true"
  />
</a>
<!-- eslint-enable svelte/no-navigation-without-resolve -->
