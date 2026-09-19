<script lang="ts">
  import type { FlowRunDebugExport } from "@eneo/eneo-js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";
  import { Badge } from "$lib/components/ui/badge/index.js";

  let {
    debugExport,
    copiedKey,
    sensitiveCareDataFlow = false,
    onDownloadCanonicalEvidence,
    onCopyPayload,
    onDownloadJsonArtifact
  }: {
    debugExport: FlowRunDebugExport | null;
    copiedKey: string | null;
    sensitiveCareDataFlow?: boolean;
    onDownloadCanonicalEvidence: () => Promise<void>;
    onCopyPayload: (key: string, payload: unknown, failureMessage: string) => Promise<void>;
    onDownloadJsonArtifact: (fileName: string, payload: unknown, failureMessage: string) => void;
  } = $props();

  const diagnosticExport = $derived(
    debugExport?.schema_version === "eneo.flow.debug-export.v3" &&
      debugExport.security.content_included === false
      ? debugExport
      : null
  );
</script>

<section
  class="border-default flex flex-col gap-3 border-b pb-4"
  aria-label={m.flow_run_debug_tools()}
>
  <p class="text-muted text-sm">{m.flow_run_debug_content_notice()}</p>
  <div class="flex flex-wrap gap-2">
    {#if diagnosticExport}
      <Button
        variant="outline"
        size="sm"
        onclick={() =>
          void onCopyPayload(
            "debug-export",
            diagnosticExport,
            m.flow_run_copy_debug_export_failed()
          )}
      >
        {copiedKey === "debug-export" ? m.copied() : m.flow_run_copy_debug_export()}
      </Button>
      <Button
        variant="outline"
        size="sm"
        onclick={() =>
          onDownloadJsonArtifact(
            `flow-debug-export-${diagnosticExport.run.run_id}.json`,
            diagnosticExport,
            m.flow_run_download_debug_export_failed()
          )}
      >
        {m.flow_run_download_debug_export()}
      </Button>
    {:else}
      <span class="text-muted text-sm">{m.flow_run_debug_content_unavailable()}</span>
    {/if}
  </div>

  {#if sensitiveCareDataFlow}
    <Badge variant="outline" class="w-fit text-xs">
      {m.flow_sensitive_evidence_export_disabled()}
    </Badge>
  {:else}
    <details class="border-default border-t pt-3">
      <summary
        class="focus-visible:outline-primary w-fit cursor-pointer rounded text-sm font-medium focus-visible:outline-2 focus-visible:outline-offset-4"
      >
        {m.flow_run_evidence_content_heading()}
      </summary>
      <p class="text-muted mt-2 max-w-prose text-sm">{m.flow_run_evidence_content_notice()}</p>
      <Button
        class="mt-3"
        variant="outline"
        size="sm"
        onclick={() => void onDownloadCanonicalEvidence()}
      >
        {m.flow_run_download_evidence_export()}
      </Button>
    </details>
  {/if}
</section>
