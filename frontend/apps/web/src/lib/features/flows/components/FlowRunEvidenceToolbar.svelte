<script lang="ts">
  import type { FlowRunDebugExport } from "@intric/intric-js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { m } from "$lib/paraglide/messages";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Card from "$lib/components/ui/card/index.js";

  let {
    debugExport,
    evidence,
    copiedKey,
    onDownloadCanonicalEvidence,
    onCopyPayload,
    onDownloadJsonArtifact
  }: {
    debugExport: FlowRunDebugExport | null;
    evidence: Record<string, unknown>;
    copiedKey: string | null;
    onDownloadCanonicalEvidence: () => Promise<void>;
    onCopyPayload: (key: string, payload: unknown, failureMessage: string) => Promise<void>;
    onDownloadJsonArtifact: (fileName: string, payload: unknown, failureMessage: string) => void;
  } = $props();

  let redactionApplied = $derived(debugExport?.security?.redaction_applied === true);
</script>

<Card.Root size="sm" class="bg-hover-dimmer">
  <Card.Content class="flex flex-col gap-3 p-3">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div class="text-muted flex flex-wrap items-center gap-2 text-[11px]">
        {#if redactionApplied}
          <Tooltip.Provider delayDuration={150}>
            <Tooltip.Root>
              <Tooltip.Trigger>
                <Badge variant="outline">{m.flow_run_evidence_redacted()}</Badge>
              </Tooltip.Trigger>
              <Tooltip.Content>{m.flow_run_evidence_redacted_tooltip()}</Tooltip.Content>
            </Tooltip.Root>
          </Tooltip.Provider>
        {/if}
        <Tooltip.Provider delayDuration={150}>
          <Tooltip.Root>
            <Tooltip.Trigger>
              <Badge variant="outline">{m.flow_run_debug_tools()}</Badge>
            </Tooltip.Trigger>
            <Tooltip.Content>{m.flow_run_debug_tools_tooltip()}</Tooltip.Content>
          </Tooltip.Root>
        </Tooltip.Provider>
      </div>

      <Button size="sm" onclick={() => void onDownloadCanonicalEvidence()}>
        {m.flow_run_download_evidence_export()}
      </Button>
    </div>

    <div class="flex flex-wrap gap-2">
      {#if debugExport}
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
  </Card.Content>
</Card.Root>
