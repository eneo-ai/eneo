<script lang="ts">
  import type { FlowRunDebugExport } from "@intric/intric-js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { m } from "$lib/paraglide/messages";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import FlowRunStatusBadge from "./FlowRunStatusBadge.svelte";

  let {
    debugExport,
    evidence,
    copiedKey,
    sensitiveCareDataFlow = false,
    runStatus,
    traceId = null,
    onDownloadCanonicalEvidence,
    onCopyPayload,
    onDownloadJsonArtifact
  }: {
    debugExport: FlowRunDebugExport | null;
    evidence: Record<string, unknown>;
    copiedKey: string | null;
    sensitiveCareDataFlow?: boolean;
    runStatus: string;
    traceId?: string | null;
    onDownloadCanonicalEvidence: () => Promise<void>;
    onCopyPayload: (key: string, payload: unknown, failureMessage: string) => Promise<void>;
    onDownloadJsonArtifact: (fileName: string, payload: unknown, failureMessage: string) => void;
  } = $props();

  let redactionApplied = $derived(debugExport?.security?.redaction_applied === true);
  let hideExportActions = $derived(sensitiveCareDataFlow);
</script>

<section
  class="border-default flex flex-col gap-3 border-b pb-4"
  aria-label={m.flow_run_debug_tools()}
>
  <div class="flex flex-wrap items-center justify-between gap-3">
    <div class="flex flex-wrap items-center gap-2">
      <FlowRunStatusBadge status={runStatus} size="md" showDot={false} />
      {#if traceId}
        <Tooltip.Provider delayDuration={150}>
          <Tooltip.Root>
            <Tooltip.Trigger>
              <Badge variant="outline" class="bg-primary text-muted font-mono text-[11px]">
                {m.flow_run_evidence_trace_id()}: {traceId}
              </Badge>
            </Tooltip.Trigger>
            <Tooltip.Content>{m.flow_run_evidence_trace_id_tooltip()}</Tooltip.Content>
          </Tooltip.Root>
        </Tooltip.Provider>
      {/if}
      {#if redactionApplied}
        <Tooltip.Provider delayDuration={150}>
          <Tooltip.Root>
            <Tooltip.Trigger>
              <Badge variant="outline" class="bg-primary text-[11px]">
                {m.flow_run_evidence_redacted()}
              </Badge>
            </Tooltip.Trigger>
            <Tooltip.Content>{m.flow_run_evidence_redacted_tooltip()}</Tooltip.Content>
          </Tooltip.Root>
        </Tooltip.Provider>
      {/if}
    </div>

    {#if hideExportActions}
      <Badge variant="outline" class="bg-primary text-muted text-[11px]">
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
