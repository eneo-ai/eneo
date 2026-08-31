<script lang="ts">
  import type { FlowRunDebugExport } from "@eneo/eneo-js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";
  import { Badge } from "$lib/components/ui/badge/index.js";

  let {
    debugExport,
    evidence,
    copiedKey,
    sensitiveCareDataFlow = false,
    onDownloadCanonicalEvidence,
    onCopyPayload,
    onDownloadJsonArtifact
  }: {
    debugExport: FlowRunDebugExport | null;
    evidence: Record<string, unknown>;
    copiedKey: string | null;
    sensitiveCareDataFlow?: boolean;
    onDownloadCanonicalEvidence: () => Promise<void>;
    onCopyPayload: (key: string, payload: unknown, failureMessage: string) => Promise<void>;
    onDownloadJsonArtifact: (fileName: string, payload: unknown, failureMessage: string) => void;
  } = $props();

  let hideExportActions = $derived(sensitiveCareDataFlow);
</script>

<section
  class="border-default flex flex-col gap-3 border-b pb-4"
  aria-label={m.flow_run_debug_tools()}
>
  <div class="flex flex-wrap items-center justify-between gap-3">
    {#if hideExportActions}
      <Badge variant="outline" class="bg-primary text-muted text-xs">
        {m.flow_sensitive_evidence_export_disabled()}
      </Badge>
    {:else}
      <Button size="sm" onclick={() => void onDownloadCanonicalEvidence()}>
        {m.flow_run_download_evidence_export()}
      </Button>
    {/if}
  </div>

  <div class="flex flex-wrap gap-2">
    {#if hideExportActions}
      <span class="text-muted text-sm">{m.flow_sensitive_artifact_access_notice()}</span>
    {:else if debugExport}
      <Button
        variant="outline"
        size="sm"
        onclick={() =>
          void onCopyPayload("debug-export", debugExport, m.flow_run_copy_debug_export_failed())}
      >
        {copiedKey === "debug-export" ? m.copied() : m.flow_run_copy_debug_export()}
      </Button>
      <Button
        variant="outline"
        size="sm"
        onclick={() =>
          onDownloadJsonArtifact(
            `flow-debug-export-${debugExport.run.run_id}.json`,
            debugExport,
            m.flow_run_download_debug_export_failed()
          )}
      >
        {m.flow_run_download_debug_export()}
      </Button>
    {/if}

    <Button
      variant="outline"
      size="sm"
      onclick={() => void onCopyPayload("full-evidence", evidence, m.flow_run_copy_failed())}
    >
      {copiedKey === "full-evidence" ? m.copied() : `${m.copy()} JSON`}
    </Button>
  </div>
</section>
