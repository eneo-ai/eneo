<script lang="ts">
  import type { FlowRunResultFile } from "@eneo/eneo-js";
  import { IconArrowDownToLine } from "@eneo/icons/arrow-down-to-line";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { m } from "$lib/paraglide/messages";

  let {
    file,
    compact = false,
    extraCount = 0,
    onDownload
  }: {
    file: FlowRunResultFile;
    compact?: boolean;
    extraCount?: number;
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
  const title = $derived(
    extraCount > 0 && isAvailable
      ? m.flow_run_artifacts_more({ first: file.name, extra: String(extraCount) })
      : label
  );
  const buttonClass = $derived(
    compact
      ? "border-default bg-primary hover:border-stronger hover:bg-hover-dimmer focus-visible:ring-accent-default/30 inline-flex h-7 items-center gap-1.5 rounded-[min(var(--radius-md),12px)] px-2.5 text-[0.8rem] font-medium transition-colors focus-visible:ring-2 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-60"
      : "group border-default bg-primary hover:border-stronger hover:bg-hover-dimmer focus-visible:ring-accent-default/30 inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium transition-colors focus-visible:ring-2 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-60"
  );
</script>

<button
  type="button"
  aria-label={label}
  {title}
  disabled={!isAvailable}
  class={buttonClass}
  onclick={() => {
    if (isAvailable) void onDownload(file.file_id);
  }}
>
  <IconArrowDownToLine
    class="{compact ? 'size-3.5' : 'size-4'} text-muted group-hover:text-secondary"
    aria-hidden="true"
  />
  <span class={compact ? "max-w-[18ch] truncate" : ""}>{file.name}</span>
  {#if extraCount > 0}
    <Badge variant="secondary" class={compact ? "ml-1 h-5 px-1.5 text-xs tabular-nums" : ""}>
      +{extraCount}
    </Badge>
  {:else if !isAvailable}
    <Badge variant="secondary">{m.flow_run_artifact_purged_badge()}</Badge>
  {:else if extension}
    <Badge class="bg-accent-dimmer text-accent-stronger">{extension}</Badge>
  {/if}
</button>
