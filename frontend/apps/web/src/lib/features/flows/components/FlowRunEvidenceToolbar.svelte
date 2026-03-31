<script lang="ts">
  import type { FlowRunDebugExport } from "@intric/intric-js";
  import { Button } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";

  export let debugExport: FlowRunDebugExport | null;
  export let evidence: Record<string, unknown>;
  export let copiedKey: string | null;
  export let onDownloadCanonicalEvidence: () => Promise<void>;
  export let onCopyPayload: (key: string, payload: unknown, failureMessage: string) => Promise<void>;
  export let onDownloadJsonArtifact: (
    fileName: string,
    payload: unknown,
    failureMessage: string
  ) => void;

  $: redactionApplied = debugExport?.security?.redaction_applied === true;
</script>

<div class="border-default bg-hover-dimmer flex flex-col gap-3 rounded-lg border p-3">
  <div class="flex flex-wrap items-center justify-between gap-2">
    <div class="text-muted flex flex-wrap items-center gap-2 text-[11px]">
      {#if redactionApplied}
        <span class="border-default bg-primary rounded-md border px-2 py-1">
          {m.flow_run_evidence_redacted()}
        </span>
      {/if}
      <span class="border-default bg-primary rounded-md border px-2 py-1">
        {m.flow_run_debug_tools()}
      </span>
    </div>

    <Button size="small" on:click={() => void onDownloadCanonicalEvidence()}>
      {m.flow_run_download_evidence_export()}
    </Button>
  </div>

  <div class="flex flex-wrap gap-2">
    {#if debugExport}
      <Button
        variant="outlined"
        size="small"
        on:click={() =>
          void onCopyPayload("debug-export", debugExport, m.flow_run_copy_debug_export_failed())}
      >
        {copiedKey === "debug-export" ? m.copied() : m.flow_run_copy_debug_export()}
      </Button>
      <Button
        variant="outlined"
        size="small"
        on:click={() =>
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
      variant="outlined"
      size="small"
      on:click={() => void onCopyPayload("full-evidence", evidence, m.flow_run_copy_failed())}
    >
      {copiedKey === "full-evidence" ? m.copied() : `${m.copy()} JSON`}
    </Button>
  </div>
</div>
