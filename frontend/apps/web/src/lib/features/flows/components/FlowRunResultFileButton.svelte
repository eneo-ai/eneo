<script lang="ts">
  import type { FlowRunResultFile } from "@eneo/eneo-js";
  import { IconArrowDownToLine } from "@eneo/icons/arrow-down-to-line";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";

  let {
    file,
    onDownload
  }: {
    file: FlowRunResultFile;
    onDownload: (fileId: string) => Promise<void> | void;
  } = $props();

  const extension = $derived(
    file.name.includes(".") ? file.name.split(".").pop()?.toLowerCase() : ""
  );
  const isAvailable = $derived(file.availability === "available");
  const label = $derived(
    isAvailable
      ? m.flow_run_download_artifact({ name: file.name })
      : m.flow_run_artifact_content_purged({ name: file.name })
  );
</script>

<Button
  variant="outline"
  aria-label={label}
  title={label}
  disabled={!isAvailable}
  onclick={() => {
    if (isAvailable) void onDownload(file.file_id);
  }}
>
  <IconArrowDownToLine data-icon="inline-start" aria-hidden="true" />
  <span class="max-w-[40ch] truncate">{file.name}</span>
  {#if !isAvailable}
    <Badge variant="secondary">{m.flow_run_artifact_purged_badge()}</Badge>
  {:else if extension}
    <Badge class="bg-accent-dimmer text-accent-stronger">{extension}</Badge>
  {/if}
</Button>
