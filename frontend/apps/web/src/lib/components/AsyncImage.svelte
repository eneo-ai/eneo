<script lang="ts">
  import placeholderImageUrl from "$lib/assets/GeneratedImagePlaceholder.svg";
  import { IconDownload } from "@intric/icons/download";
  import { Button } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    url: string | null;
    fixedAspectRatio?: false | string;
  };

  const { url, fixedAspectRatio = "800 / 608" }: Props = $props();
</script>

<div
  class="group relative overflow-clip rounded-lg"
  style={fixedAspectRatio ? `aspect-ratio: ${fixedAspectRatio};` : undefined}
>
  <img
    src={placeholderImageUrl}
    class=" bg-secondary absolute m-0 animate-pulse p-0"
    alt={m.placeholder()}
  />
  {#if url}
    <img
      src={url}
      class="relative m-0 p-0 transition-opacity duration-200"
      style="opacity: 0; "
      onload={(ev) => {
        const target = ev.target as HTMLImageElement;
        if (target) {
          target.style.opacity = "1";
        }
      }}
      alt={m.generated_file()}
    />
    <Button
      href={url}
      unstyled
      variant="outlined"
      class="border-stronger bg-secondary hover:bg-tertiary absolute top-2 right-2 hidden gap-1 rounded-md border px-2 py-1 no-underline shadow group-hover:flex"
      ><IconDownload></IconDownload>{m.download_file()}</Button
    >
  {/if}
</div>
