<script lang="ts">
  import { IconChevronDown } from "@eneo/icons/chevron-down";
  import { IconCopy } from "@eneo/icons/copy";
  import { IconCheck } from "@eneo/icons/check";
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import { Markdown } from "@eneo/ui";
  import { slide, fade } from "svelte/transition";
  import { cubicOut } from "svelte/easing";
  import { browser } from "$app/environment";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { getLocale } from "$lib/paraglide/runtime";
  import { formatFlowRunTokenCount } from "./flowRunTokenUsage";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import { m } from "$lib/paraglide/messages";
  import type { FlowRunProgressStep } from "./flowRunProgress";
  import { formatFlowRunStepDuration } from "./flowRunProgress";
  import FlowRunResultFileButton from "./FlowRunResultFileButton.svelte";
  import FlowRunStatusBadge from "./FlowRunStatusBadge.svelte";
  import FlowRunErrorAlert from "./FlowRunErrorAlert.svelte";

  let {
    step,
    expanded,
    focused = false,
    inputExpanded,
    copiedKey,
    panelId,
    onToggle,
    onToggleInput,
    onCopyPayload,
    onDownloadArtifact
  }: {
    step: FlowRunProgressStep;
    expanded: boolean;
    focused?: boolean;
    inputExpanded: boolean;
    copiedKey: string | null;
    panelId: string;
    onToggle: (stepOrder: number) => void;
    onToggleInput: (stepOrder: number) => void;
    onCopyPayload: (key: string, payload: unknown) => Promise<void>;
    onDownloadArtifact: (fileId: string) => Promise<void>;
  } = $props();

  const prefersReducedMotion =
    browser && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const isRunning = $derived(step.status === "running");
  const isCompleted = $derived(step.status === "completed");
  const isFailed = $derived(step.status === "failed" || step.status === "cancelled");
  const canExpand = $derived(isCompleted || isFailed || isRunning);

  const duration = $derived(formatFlowRunStepDuration(step));

  const circleClass = $derived.by(() => {
    if (isRunning) return "bg-accent-dimmer text-accent-stronger";
    if (isCompleted) return "bg-positive-dimmer text-positive-stronger";
    if (isFailed) return "bg-negative-dimmer text-negative-stronger";
    return "bg-hover-dimmer";
  });

  const hasStructuredOutput = $derived(
    step.outputPayload?.structured !== undefined && step.outputPayload?.structured !== null
  );
  const hasResultFiles = $derived(step.resultFiles.length > 0);
  const hasTextOutput = $derived(
    typeof step.outputPayload?.text === "string" && step.outputPayload.text.length > 0
  );
  const hasOutput = $derived(hasStructuredOutput || hasResultFiles || hasTextOutput);
  const hasInput = $derived(step.inputPayload != null);
  // Steps without a model call (transcription, template fill) report 0/0.
  const hasTokens = $derived((step.numTokensInput ?? 0) + (step.numTokensOutput ?? 0) > 0);
</script>

<Card.Root
  class="gap-0 overflow-hidden py-0 motion-safe:transition-[background-color,border-color] motion-safe:duration-(--duration-fast) {focused
    ? 'border-accent-default/40 bg-accent-dimmer/15'
    : ''} {isRunning ? 'ring-accent-default/35 ring-2' : ''} {isFailed
    ? 'ring-negative-default/30 ring-1'
    : ''}"
>
  <button
    type="button"
    class="focus-visible:inset-ring-ring flex w-full items-center justify-between gap-3 px-4 py-3 text-left focus-visible:inset-ring-2 focus-visible:outline-none disabled:cursor-default"
    aria-expanded={expanded}
    aria-controls={panelId}
    aria-current={focused ? "step" : undefined}
    disabled={!canExpand}
    onclick={() => {
      if (canExpand) onToggle(step.stepOrder);
    }}
  >
    <div class="flex min-w-0 items-center gap-3">
      <span
        class="{circleClass} flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold tabular-nums motion-safe:transition-colors motion-safe:duration-(--duration-fast)"
      >
        {step.stepOrder}
      </span>
      <div class="min-w-0 flex-1">
        <div class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
          <span class="truncate text-sm font-medium">{step.label}</span>
          <FlowRunStatusBadge
            status={step.status}
            size="xs"
            class="shrink-0"
            pulsing={isRunning && !expanded}
          />
          {#if duration}
            <span class="text-secondary shrink-0 text-xs tabular-nums">{duration}</span>
          {/if}
        </div>
        {#if focused && step.status === "queued"}
          <p class="text-secondary mt-1 text-xs">
            {m.flow_run_progress_next_step_hint()}
          </p>
        {/if}
      </div>
    </div>
    <div class="flex shrink-0 items-center gap-2">
      {#if canExpand}
        <span
          class="text-muted motion-safe:transition-transform motion-safe:duration-(--duration-quick) motion-safe:ease-(--ease-smooth-out)"
          class:rotate-180={expanded}
          aria-hidden="true"
        >
          <IconChevronDown class="size-4" />
        </span>
      {/if}
    </div>
  </button>

  {#if expanded && canExpand}
    <div
      id={panelId}
      transition:slide={{ duration: prefersReducedMotion ? 0 : 150, easing: cubicOut }}
    >
      <Card.Content class="border-default flex min-w-0 flex-col gap-3 border-t px-4 py-3">
        {#if step.errorMessage}
          <FlowRunErrorAlert errorCode={step.errorCode} message={step.errorMessage} />
        {/if}

        {#if hasOutput}
          <div>
            <div class="flex items-center justify-between">
              <h4 class="text-secondary text-xs font-semibold">{m.flow_run_output()}</h4>
              <Button
                variant="ghost"
                size="icon"
                class="text-secondary hover:text-primary size-8"
                aria-label={m.copy()}
                onclick={() =>
                  void onCopyPayload(`progress-step-${step.stepOrder}-output`, step.outputPayload)}
              >
                {#if copiedKey === `progress-step-${step.stepOrder}-output`}
                  <span in:fade={{ duration: prefersReducedMotion ? 0 : 150 }}
                    ><IconCheck class="text-positive-stronger size-3.5" /></span
                  >
                {:else}
                  <IconCopy class="size-3.5" />
                {/if}
              </Button>
            </div>

            {#if hasStructuredOutput && step.outputPayload?.structured !== undefined}
              <div class="mt-1">
                <Badge class="bg-accent-dimmer text-accent-stronger mb-1">
                  {m.flow_run_structured_json_badge()}
                </Badge>
                <pre
                  class="bg-hover-dimmer max-h-80 overflow-auto rounded-lg p-3 font-mono text-[13px] leading-relaxed break-words whitespace-pre-wrap">{JSON.stringify(
                    step.outputPayload.structured,
                    null,
                    2
                  )}</pre>
              </div>
            {/if}

            {#if hasResultFiles}
              <div class="mt-2">
                <h4 class="text-secondary text-xs font-semibold">{m.flow_run_files()}</h4>
                <div class="mt-1.5 flex flex-wrap gap-2">
                  {#each step.resultFiles as artifact (artifact.file_id)}
                    <FlowRunResultFileButton file={artifact} onDownload={onDownloadArtifact} />
                  {/each}
                </div>
              </div>
            {/if}

            {#if hasTextOutput && !hasStructuredOutput && !hasResultFiles}
              <div class="bg-hover-dimmer mt-1 max-h-96 overflow-auto rounded-lg p-4">
                <Markdown source={step.outputPayload?.text ?? ""} class="text-sm" />
              </div>
            {/if}
          </div>
        {:else if isRunning}
          <!-- The badge already says the step runs; the body says what that
               means for the reader instead of drawing placeholder text. -->
          <p class="text-secondary flex items-center gap-2 text-sm">
            <IconLoadingSpinner class="size-3.5 shrink-0 motion-safe:animate-spin" />
            {step.speakerIdentification
              ? m.flow_run_progress_transcribing_with_speakers_hint()
              : m.flow_run_progress_running_body()}
          </p>
        {:else if isCompleted && step.detailsStale}
          <div class="text-secondary text-xs italic">
            {m.flow_run_progress_details_stale()}
          </div>
        {:else if isCompleted}
          <div class="text-secondary text-xs italic">
            {m.flow_run_progress_empty_output()}
          </div>
        {/if}

        {#if hasInput}
          <Collapsible.Root open={inputExpanded} onOpenChange={() => onToggleInput(step.stepOrder)}>
            <div class="flex items-center justify-between">
              <Collapsible.Trigger
                class="text-secondary hover:text-primary focus-visible:ring-ring -ml-1 flex items-center gap-1.5 rounded-md px-1 py-0.5 text-xs font-semibold transition-colors focus-visible:ring-2 focus-visible:outline-none"
              >
                <IconChevronDown
                  class="size-3 motion-safe:transition-transform motion-safe:duration-(--duration-quick) motion-safe:ease-(--ease-smooth-out) {inputExpanded
                    ? ''
                    : '-rotate-90'}"
                />
                {m.flow_run_input()}
              </Collapsible.Trigger>
              <Button
                variant="ghost"
                size="icon"
                class="text-secondary hover:text-primary size-8"
                aria-label={m.copy()}
                onclick={() =>
                  void onCopyPayload(`progress-step-${step.stepOrder}-input`, step.inputPayload)}
              >
                {#if copiedKey === `progress-step-${step.stepOrder}-input`}
                  <span in:fade={{ duration: prefersReducedMotion ? 0 : 150 }}
                    ><IconCheck class="text-positive-stronger size-3.5" /></span
                  >
                {:else}
                  <IconCopy class="size-3.5" />
                {/if}
              </Button>
            </div>
            <Collapsible.Content>
              <pre
                id="progress-step-{step.stepOrder}-input-panel"
                class="bg-hover-dimmer mt-1 max-h-80 overflow-auto rounded-lg p-3 font-mono text-[13px] leading-relaxed break-words whitespace-pre-wrap">{JSON.stringify(
                  step.inputPayload,
                  null,
                  2
                )}</pre>
            </Collapsible.Content>
          </Collapsible.Root>
        {/if}

        {#if hasTokens}
          <div class="border-default text-secondary flex items-center gap-2 border-t pt-3 text-xs">
            <span>{m.flow_run_tokens()}</span>
            <span aria-hidden="true">&middot;</span>
            <span class="tabular-nums"
              >{m.flow_run_tokens_in({
                count: formatFlowRunTokenCount(step.numTokensInput ?? 0, getLocale())
              })}</span
            >
            <span aria-hidden="true">&middot;</span>
            <span class="tabular-nums"
              >{m.flow_run_tokens_out({
                count: formatFlowRunTokenCount(step.numTokensOutput ?? 0, getLocale())
              })}</span
            >
          </div>
        {/if}
      </Card.Content>
    </div>
  {/if}
</Card.Root>
