<svelte:options runes={false} />

<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Button } from "@intric/ui";
  import type { HttpAuthoredConfig, HttpDirection, HttpMethod } from "./httpConfigTypes";
  import { Card } from "@eneo/ui";

  export let config: HttpAuthoredConfig;
  export let direction: HttpDirection;
  export let method: HttpMethod;
  export let flowId: string;
  export let isPublished: boolean;

  let testing = false;
  let result: {
    success: boolean;
    status_code?: number | null;
    duration_ms?: number;
    response_preview?: string | null;
    error_code?: string | null;
    error_message?: string | null;
  } | null = null;

  async function runTest() {
    if (!config.url.trim()) return;
    testing = true;
    result = null;

    try {
      const response = await fetch(`/api/v1/flows/${flowId}/http-test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          config,
          direction,
          method,
          test_variables: {}
        })
      });
      result = await response.json();
    } catch (err) {
      result = {
        success: false,
        error_message: err instanceof Error ? err.message : "Unknown error"
      };
    } finally {
      testing = false;
    }
  }
</script>

<div class="flex flex-col gap-3">
  <div class="flex items-center gap-3">
    <Button
      variant="outlined"
      size="small"
      disabled={isPublished || testing || !config.url.trim()}
      on:click={runTest}
    >
      {#if testing}
        {m.http_test_testing()}
      {:else}
        {m.http_test_button()}
      {/if}
    </Button>
    {#if result}
      <span
        class="text-xs font-medium {result.success
          ? 'text-accent-default'
          : 'text-danger-default'}"
      >
        {#if result.success}
          {result.status_code}
          {#if result.duration_ms}
            &middot; {Math.round(result.duration_ms)}ms
          {/if}
        {:else}
          {result.error_message ?? result.error_code ?? "Error"}
        {/if}
      </span>
    {/if}
  </div>
  {#if result?.response_preview}
    <Card.Root>
      <Card.Content class="max-h-[120px] overflow-auto p-3">
        <pre class="font-mono text-xs">{result.response_preview}</pre>
      </Card.Content>
    </Card.Root>
  {/if}
</div>
