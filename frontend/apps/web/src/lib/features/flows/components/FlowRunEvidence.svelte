<script lang="ts">
  import type { Intric, FlowStepResult } from "@intric/intric-js";
  import { IconChevronDown } from "@intric/icons/chevron-down";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { Button } from "@intric/ui";
  import { onDestroy, onMount } from "svelte";
  import { slide } from "svelte/transition";
  import { m } from "$lib/paraglide/messages";
  import { getFlowUserMode } from "$lib/features/flows/FlowUserMode";

  export let runId: string;
  export let intric: Intric;
  export let runStatus: string;

  let evidence: {
    run: Record<string, unknown>;
    definition_snapshot: Record<string, unknown>;
    step_results: FlowStepResult[];
    step_attempts: Record<string, unknown>[];
  } | null = null;
  let loading = true;
  let loadError = false;
  let expandedSteps: number[] = [];
  let copiedKey: string | null = null;
  let copiedTimer: ReturnType<typeof setTimeout> | null = null;
  const mode = getFlowUserMode();
  let stepAttemptsByOrder: Record<number, Record<string, unknown>[]> = {};

  onMount(async () => {
    try {
      evidence = await intric.flows.runs.evidence({ id: runId });
    } catch (e) {
      console.error("Error loading evidence", e);
      loadError = true;
    }
    loading = false;
  });

  let lastFetchedStatus: string | null = null;

  $: if (runStatus && evidence && lastFetchedStatus !== runStatus &&
      (runStatus === "completed" || runStatus === "failed" || runStatus === "cancelled")) {
    lastFetchedStatus = runStatus;
    void refetchEvidence();
  }

  async function refetchEvidence() {
    try {
      evidence = await intric.flows.runs.evidence({ id: runId });
    } catch { /* ignore — already have stale data */ }
  }

  onDestroy(() => {
    if (copiedTimer) clearTimeout(copiedTimer);
  });

  function toggleStep(order: number) {
    const hasOrder = expandedSteps.includes(order);
    if (hasOrder) {
      expandedSteps = expandedSteps.filter((item) => item !== order);
    } else {
      expandedSteps = [...expandedSteps, order];
    }
  }

  function getStatusColor(status: string): string {
    switch (status) {
      case "completed": return "text-green-600";
      case "failed": return "text-red-600";
      case "running": return "text-blue-600";
      case "pending": return "text-gray-500";
      default: return "text-gray-500";
    }
  }

  function getStatusLabel(status: string): string {
    switch (status) {
      case "completed": return m.flow_run_status_completed();
      case "failed": return m.flow_run_status_failed();
      case "running": return m.flow_run_status_running();
      case "pending": return m.flow_run_status_queued();
      default: return status;
    }
  }

  function setCopied(key: string) {
    copiedKey = key;
    if (copiedTimer) clearTimeout(copiedTimer);
    copiedTimer = setTimeout(() => {
      copiedKey = null;
    }, 1200);
  }

  async function copyPayload(key: string, payload: unknown) {
    try {
      const rendered = typeof payload === "string" ? payload : JSON.stringify(payload, null, 2);
      await navigator.clipboard.writeText(rendered);
      setCopied(key);
    } catch (error) {
      console.error("Could not copy evidence payload", error);
    }
  }

  function getStepAttempts(stepOrder: number): Record<string, unknown>[] {
    return stepAttemptsByOrder[stepOrder] ?? [];
  }

  function getStepDuration(stepOrder: number): string | null {
    const attempts = getStepAttempts(stepOrder);
    if (attempts.length === 0) return null;
    const first = attempts[0] as { started_at?: string; finished_at?: string };
    const last = attempts[attempts.length - 1] as { started_at?: string; finished_at?: string };
    if (!first.started_at || !last.finished_at) return null;
    const ms = new Date(last.finished_at).getTime() - new Date(first.started_at).getTime();
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    return `${(ms / 60000).toFixed(1)}m`;
  }

  async function downloadArtifact(fileId: string) {
    try {
      const { url } = await intric.files.generateSignedUrl({
        fileId,
        contentDisposition: "attachment",
      });
      window.open(url, "_blank");
    } catch (e) {
      console.error("Failed to download artifact", e);
    }
  }

  $: stepAttemptsByOrder = (() => {
    const grouped: Record<number, Record<string, unknown>[]> = {};
    for (const attempt of evidence?.step_attempts ?? []) {
      const stepOrder = Number((attempt as { step_order?: unknown }).step_order ?? 0);
      grouped[stepOrder] ??= [];
      grouped[stepOrder].push(attempt);
    }
    return grouped;
  })();
</script>

{#if loading}
  <div class="flex items-center gap-2 text-sm text-secondary">
    <IconLoadingSpinner class="size-4 animate-spin" />
    {m.flow_run_evidence_loading()}
  </div>
{:else if loadError || evidence === null}
  <p class="text-sm text-negative-default">{m.flow_run_evidence_error()}</p>
{:else}
  <div class="flex flex-col gap-2">
    <div class="flex justify-end">
      <Button variant="outlined" size="small" on:click={() => copyPayload("full-evidence", evidence)}>
        {copiedKey === "full-evidence" ? m.copied() : `${m.copy()} JSON`}
      </Button>
    </div>

    {#each evidence.step_results as result (result.id ?? result.step_order)}
      {@const stepDef = ((evidence.definition_snapshot?.steps ?? []) as any[]).find(
        (s) => s.step_order === result.step_order
      )}
      {@const duration = getStepDuration(result.step_order)}
      <div class="bg-primary border-default overflow-hidden rounded-lg border shadow-sm transition-shadow hover:shadow-md">
        <button
          class="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-hover-dimmer"
          on:click={() => toggleStep(result.step_order)}
        >
          <div class="flex items-center gap-2">
            <span class="bg-hover-default flex size-5 items-center justify-center rounded text-xs font-bold">
              {result.step_order}
            </span>
            <span class="text-sm font-medium">
              {stepDef?.user_description ?? m.flow_step_fallback_label({ order: String(result.step_order) })}
            </span>
            <span class="{getStatusColor(result.status)} text-xs font-medium">{getStatusLabel(result.status)}</span>
            {#if duration}
              <span class="text-xs tabular-nums text-secondary">{duration}</span>
            {/if}
          </div>
          <span class="transition-transform" class:rotate-180={expandedSteps.includes(result.step_order)}>
            <IconChevronDown class="size-4" />
          </span>
        </button>

        {#if expandedSteps.includes(result.step_order)}
          <div transition:slide={{ duration: 200 }}>
            <div class="border-default flex min-w-0 flex-col gap-3 border-t px-4 py-3">
              {#if result.effective_prompt}
                <div>
                  <div class="flex items-center justify-between">
                    <h4 class="text-xs font-semibold uppercase tracking-wider text-secondary">{m.flow_run_effective_prompt()}</h4>
                    <Button
                      variant="outlined"
                      size="small"
                      class={copiedKey === `step-${result.step_order}-prompt` ? 'text-positive-default' : ''}
                      on:click={() => copyPayload(`step-${result.step_order}-prompt`, result.effective_prompt)}
                    >
                      {copiedKey === `step-${result.step_order}-prompt` ? m.copied() : m.copy()}
                    </Button>
                  </div>
                  <pre class="bg-hover-dimmer mt-1 max-h-60 overflow-auto whitespace-pre-wrap break-words rounded-md p-3 text-sm">{result.effective_prompt}</pre>
                </div>
              {/if}

              {#if result.input_payload_json}
                <div>
                  <div class="flex items-center justify-between">
                    <h4 class="text-xs font-semibold uppercase tracking-wider text-secondary">{m.flow_run_input()}</h4>
                    <Button
                      variant="outlined"
                      size="small"
                      class={copiedKey === `step-${result.step_order}-input` ? 'text-positive-default' : ''}
                      on:click={() => copyPayload(`step-${result.step_order}-input`, result.input_payload_json)}
                    >
                      {copiedKey === `step-${result.step_order}-input` ? m.copied() : m.copy()}
                    </Button>
                  </div>
                  <pre class="bg-hover-dimmer mt-1 max-h-60 overflow-auto whitespace-pre-wrap break-words rounded-md p-3 font-mono text-xs">{JSON.stringify(result.input_payload_json, null, 2)}</pre>
                </div>
              {/if}

              {#if result.output_payload_json}
                <div>
                  <div class="flex items-center justify-between">
                    <h4 class="text-xs font-semibold uppercase tracking-wider text-secondary">{m.flow_run_output()}</h4>
                    <Button
                      variant="outlined"
                      size="small"
                      class={copiedKey === `step-${result.step_order}-output` ? 'text-positive-default' : ''}
                      on:click={() => copyPayload(`step-${result.step_order}-output`, result.output_payload_json)}
                    >
                      {copiedKey === `step-${result.step_order}-output` ? m.copied() : m.copy()}
                    </Button>
                  </div>

                  {#if result.output_payload_json.structured}
                    <div class="mt-1">
                      <span class="mb-1 inline-block rounded bg-purple-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-purple-700">JSON</span>
                      <pre class="bg-hover-dimmer max-h-60 overflow-auto whitespace-pre-wrap break-words rounded-md p-3 font-mono text-sm">{JSON.stringify(result.output_payload_json.structured, null, 2)}</pre>
                    </div>
                  {/if}

                  {#if result.output_payload_json.artifacts?.length}
                    <div class="mt-2 flex flex-wrap gap-2">
                      {#each result.output_payload_json.artifacts as artifact}
                        <button
                          class="inline-flex items-center gap-1.5 rounded-md border border-default bg-primary px-3 py-1.5 text-xs font-medium shadow-sm transition-colors hover:bg-hover-dimmer"
                          on:click={() => downloadArtifact(artifact.file_id)}
                        >
                          <span>{m.download()}</span>
                          <span class="text-secondary">{artifact.name}</span>
                        </button>
                      {/each}
                    </div>
                  {/if}

                  {#if result.output_payload_json.text && !result.output_payload_json.structured}
                    <pre class="bg-hover-dimmer mt-1 max-h-60 overflow-auto whitespace-pre-wrap break-words rounded-md p-3 font-mono text-xs">{result.output_payload_json.text}</pre>
                  {:else if !result.output_payload_json.structured && !result.output_payload_json.artifacts?.length}
                    <pre class="bg-hover-dimmer mt-1 max-h-60 overflow-auto whitespace-pre-wrap break-words rounded-md p-3 font-mono text-xs">{JSON.stringify(result.output_payload_json, null, 2)}</pre>
                  {/if}
                </div>
              {/if}

              {#if $mode === "power_user" && getStepAttempts(result.step_order).length > 0}
                <div>
                  <div class="flex items-center justify-between">
                    <h4 class="text-xs font-semibold uppercase tracking-wider text-secondary">{m.flow_run_attempts()}</h4>
                    <Button
                      variant="outlined"
                      size="small"
                      class={copiedKey === `step-${result.step_order}-attempts` ? 'text-positive-default' : ''}
                      on:click={() => copyPayload(`step-${result.step_order}-attempts`, getStepAttempts(result.step_order))}
                    >
                      {copiedKey === `step-${result.step_order}-attempts` ? m.copied() : m.copy()}
                    </Button>
                  </div>
                  <pre class="bg-hover-dimmer mt-1 max-h-60 overflow-auto whitespace-pre-wrap break-words rounded-md p-3 font-mono text-xs">{JSON.stringify(getStepAttempts(result.step_order), null, 2)}</pre>
                </div>
              {/if}

              <div class="flex gap-4 text-xs text-secondary">
                {#if result.num_tokens_input != null || result.num_tokens_output != null}
                  <span>{m.flow_run_tokens()}: {result.num_tokens_input ?? 0} in / {result.num_tokens_output ?? 0} out</span>
                {/if}
              </div>

              {#if result.error_message}
                <div>
                  <h4 class="text-xs font-semibold uppercase tracking-wider text-red-600">{m.flow_run_error()}</h4>
                  <pre class="mt-1 max-h-60 overflow-auto whitespace-pre-wrap break-words rounded-md bg-red-50 p-3 font-mono text-xs text-red-700">{result.error_message}</pre>
                </div>
              {/if}
            </div>
          </div>
        {/if}
      </div>
    {/each}
  </div>
{/if}
