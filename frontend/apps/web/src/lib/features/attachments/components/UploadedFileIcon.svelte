<script lang="ts">
  import { IconFile } from "@eneo/icons/file";
  import { IconFileAudio } from "@eneo/icons/file-audio";
  import { IconFileImage } from "@eneo/icons/file-image";
  import { IconFileText } from "@eneo/icons/file-text";
  import type { ClassValue } from "svelte/elements";

  const icons = {
    image: IconFileImage,
    audio: IconFileAudio,
    // We only support audio, but webm has video as mime type
    video: IconFileAudio,
    text: IconFileText,
    fallback: IconFile
  };

  type Props = {
    file?: { mimetype: string };
    class?: ClassValue;
  };

  const { file, class: cls }: Props = $props();
  const Icon = $derived.by(() => {
    if (!file) return icons.fallback;
    // (e.g., "image" from "image/jpeg")
    const generalType = file.mimetype.split("/")[0];
    // @ts-expect-error We dont care about index signature in this case
    return icons[generalType] || icons.fallback;
  });
</script>

<Icon class={cls}></Icon>
