<!-- Test-only host: exposes the bound file list and rejections to the test. -->
<script lang="ts">
  import type { FormatLimit } from "../fileFormatSummary";
  import FileDropzone from "./FileDropzone.svelte";

  type Props = {
    formats: FormatLimit[];
    onfilesrejected?: (rejectedFiles: File[]) => void;
    onfileschanged?: (files: File[]) => void;
  };

  const { formats, onfilesrejected, onfileschanged }: Props = $props();

  let files = $state<File[]>([]);

  $effect(() => {
    onfileschanged?.([...files]);
  });
</script>

<FileDropzone bind:files {formats} {onfilesrejected} />
