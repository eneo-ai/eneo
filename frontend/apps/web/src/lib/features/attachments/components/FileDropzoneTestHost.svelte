<!-- Test-only host: exposes the bound file list and selections to the test. -->
<script lang="ts">
  import type { AcceptedFormat } from "../AttachmentManager";
  import FileDropzone, { type FileSelection } from "./FileDropzone.svelte";

  type Props = {
    formats: AcceptedFormat[];
    multiple?: boolean;
    keepSelection?: boolean;
    onselect?: (selection: FileSelection) => void;
    onfileschanged?: (files: File[]) => void;
  };

  const { formats, multiple, keepSelection, onselect, onfileschanged }: Props = $props();

  let files = $state<File[]>([]);

  $effect(() => {
    onfileschanged?.([...files]);
  });
</script>

<FileDropzone bind:files {formats} {multiple} {keepSelection} {onselect} />
