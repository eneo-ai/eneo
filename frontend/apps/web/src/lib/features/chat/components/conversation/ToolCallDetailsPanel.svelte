<!--
  Copyright (c) 2026 Sundsvalls Kommun

  Expanded detail panel for a tool call: parameters JSON and the lazily
  fetched result. Shared by ReasoningToolStep and InternalToolStep. The
  component stays mounted while `open` toggles so the fetch state survives
  collapse/expand and cached results are not refetched.
-->
<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";
  import { Wrench } from "lucide-svelte";

  type Status = "preparing" | "running" | "complete" | "failed" | "denied";

  let {
    open,
    toolName,
    args,
    toolCallId,
    onLoadResult,
    status = "complete",
    containerClass = "border-dimmer border-t px-3 py-2.5"
  }: {
    open: boolean;
    /** Display name used in the "Response from {toolName}" heading. */
    toolName: string;
    args?: Record<string, unknown>;
    toolCallId?: string;
    onLoadResult?: () => Promise<string | null>;
    status?: Status;
    containerClass?: string;
  } = $props();

  let result = $state<string | null>(null);
  let resultLoaded = $state(false);
  let resultLoading = $state(false);
  const hasArgs = $derived(args != null && Object.keys(args).length > 0);
  const canViewResult = $derived(
    !!toolCallId && !!onLoadResult && (status === "complete" || status === "failed")
  );

  async function loadResult(force = false) {
    if (resultLoading || (resultLoaded && !force) || !onLoadResult) return;

    resultLoading = true;
    try {
      result = await onLoadResult();
    } catch (error) {
      // A failed automatic attempt stays silent: mid-stream the result is
      // simply not persisted yet (404), and toasting would fire on every
      // still-streaming turn. Manual re-expands (force) surface real errors.
      if (force) toastError(error, m.mcp_tool_response_load_error());
    } finally {
      // Attempted is attempted, success or not — the automatic path below
      // must never retry on its own, or a pending result becomes a request
      // loop against the 404ing result endpoint.
      resultLoaded = true;
      resultLoading = false;
    }
  }

  let wasOpen = false;
  $effect(() => {
    if (open && canViewResult) {
      if (!wasOpen) {
        // An open transition retries when nothing was captured (e.g. the
        // first attempt ran before the stream persisted the result) and
        // surfaces real errors.
        void loadResult(result == null);
      } else if (!resultLoaded) {
        // The result became viewable while already open (status flipped to
        // complete/failed): load it silently.
        void loadResult();
      }
    }
    wasOpen = open;
  });
</script>

{#if open}
  <div class={containerClass}>
    {#if hasArgs}
      <div class="text-muted mb-1.5 flex items-center gap-1.5 text-xs font-semibold">
        <Wrench class="h-3 w-3 shrink-0" />
        <span>{m.chat_reasoning_parameters()}</span>
      </div>
      <pre
        class="bg-primary/60 text-secondary overflow-x-auto rounded-md p-2.5 font-mono text-xs whitespace-pre-wrap">{JSON.stringify(
          args,
          null,
          2
        )}</pre>
    {/if}

    {#if canViewResult}
      <div class={hasArgs ? "border-dimmer mt-2.5 border-t pt-2.5" : ""}>
        <div class="text-muted mb-1.5 text-xs font-semibold">
          {m.mcp_tool_response_title({ toolName })}
        </div>
        {#if resultLoading}
          <p class="text-muted text-xs">{m.loading_ellipsis()}</p>
        {:else if resultLoaded && result}
          <pre
            class="bg-primary/60 text-secondary max-h-72 overflow-auto rounded-md p-2.5 font-mono text-xs whitespace-pre-wrap">{result}</pre>
        {:else if resultLoaded}
          <p class="text-muted text-xs italic">{m.mcp_tool_response_empty()}</p>
        {/if}
      </div>
    {/if}
  </div>
{/if}
