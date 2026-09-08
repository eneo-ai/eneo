<script lang="ts">
  import placeholderImageUrl from "$lib/assets/GeneratedImagePlaceholder.svg";
  import { IconDownload } from "@eneo/icons/download";
  import { Button } from "@eneo/ui";
  import { sanitizeImageSrc, sanitizeLinkHref } from "@eneo/ui/components/markdown";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    url: string | null;
    fixedAspectRatio?: false | string;
  };

  const { url, fixedAspectRatio = "800 / 608" }: Props = $props();
  const safeImageUrl = $derived(sanitizeImageSrc(url));
  const safeDownloadUrl = $derived(sanitizeLinkHref(url));
  // The reserved aspect ratio only holds space while loading. Once the real
  // image is in, the box follows the image: a wider image than the reserved
  // ratio would otherwise leave the placeholder showing beneath it.
  let loaded = $state(false);
</script>

<div
  class="group relative overflow-clip rounded-lg"
  style={fixedAspectRatio && !loaded ? `aspect-ratio: ${fixedAspectRatio};` : undefined}
>
  {#if !loaded}
    <img
      src={placeholderImageUrl}
      class=" bg-secondary absolute m-0 animate-pulse p-0"
      alt={m.placeholder()}
    />
  {/if}
  {#if safeImageUrl}
    <img
      src={safeImageUrl}
      class="relative m-0 p-0 transition-opacity duration-200"
      style="opacity: 0; "
      onload={(ev) => {
        const target = ev.target as HTMLImageElement;
        if (target) {
          target.style.opacity = "1";
        }
        loaded = true;
      }}
      alt={m.generated_file()}
    />
    {#if safeDownloadUrl}
      <Button
        href={safeDownloadUrl}
        unstyled
        variant="outlined"
        class="border-stronger bg-secondary hover:bg-tertiary absolute top-2 right-2 hidden gap-1 rounded-md border px-2 py-1 no-underline shadow group-hover:flex"
        ><IconDownload></IconDownload>{m.download_file()}</Button
      >
    {/if}
  {/if}
</div>
