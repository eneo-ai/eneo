<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import type {
    FlowHttpRequestPreview,
    FlowHttpTestRequest,
    FlowHttpTestResponse
  } from "@eneo/eneo-js";
  import type { HttpAuthoredConfig, HttpDirection, HttpMethod } from "./httpConfigTypes";
  import { parseHttpTestVariables } from "./httpTestVariables";

  let {
    config,
    direction,
    method,
    flowId,
    isPublished
  }: {
    config: HttpAuthoredConfig;
    direction: HttpDirection;
    method: HttpMethod;
    flowId: string;
    isPublished: boolean;
  } = $props();

  let testing = $state(false);
  let testVariablesText = $state("{}");
  let result: FlowHttpTestResponse | null = $state(null);

  const hasTemplateMarkers = $derived.by(() => JSON.stringify(config).includes("{{"));

  async function runTest() {
    if (!config.url.trim()) return;

    const parsedVariables = hasTemplateMarkers
      ? parseHttpTestVariables(testVariablesText)
      : { ok: true as const, value: {} };
    if (!parsedVariables.ok) {
      result = localError(m.http_test_variables_invalid());
      return;
    }

    testing = true;
    result = null;

    try {
      const body: FlowHttpTestRequest = {
        config,
        direction,
        method,
        test_variables: parsedVariables.value
      };
      const response = await fetch(`/api/v1/flows/${flowId}/http-test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
      if (!response.ok) {
        const payload: unknown = await response.json().catch(() => null);
        result = localError(apiEnvelopeMessage(response, payload));
        return;
      }

      const payload: FlowHttpTestResponse = await response.json();
      result = payload;
    } catch (err) {
      result = localError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      testing = false;
    }
  }

  function localError(message: string): FlowHttpTestResponse {
    return { success: false, error_message: message };
  }

  function apiEnvelopeMessage(response: Response, payload: unknown): string {
    const envelopeMessage = readEnvelopeMessage(payload);
    if (envelopeMessage) return `${response.status}: ${envelopeMessage}`;
    if (response.statusText) return `${response.status} ${response.statusText}`;
    return m.http_test_request_failed({ status: response.status });
  }

  function readEnvelopeMessage(payload: unknown): string | null {
    if (!isRecord(payload)) return null;
    if (typeof payload.detail === "string") return payload.detail;
    if (typeof payload.message === "string") return payload.message;
    return null;
  }

  function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === "object" && value !== null && !Array.isArray(value);
  }

  function formatPreviewHeaders(preview: FlowHttpRequestPreview): string {
    return JSON.stringify(preview.headers, null, 2);
  }
</script>

<div class="flex flex-col gap-3">
  {#if hasTemplateMarkers}
    <label class="flex flex-col gap-1.5">
      <span class="text-xs font-medium">{m.http_test_variables_label()}</span>
      <Textarea
        class="min-h-[80px] font-mono text-xs"
        aria-label={m.http_test_variables_label()}
        value={testVariablesText}
        disabled={isPublished || testing}
        placeholder={m.http_test_variables_placeholder()}
        oninput={(e) => (testVariablesText = e.currentTarget.value)}
      />
      <span class="text-muted text-xs leading-relaxed">{m.http_test_variables_help()}</span>
    </label>
  {/if}

  <div class="flex items-center gap-3">
    <Button
      variant="outline"
      size="sm"
      disabled={isPublished || testing || !config.url.trim()}
      onclick={runTest}
    >
      {#if testing}
        {m.http_test_testing()}
      {:else}
        {m.http_test_button()}
      {/if}
    </Button>
    {#if result}
      <span
        class="text-xs font-medium {result.success ? 'text-accent-default' : 'text-danger-default'}"
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
  {#if result?.request_preview}
    <Card.Root>
      <Card.Content class="max-h-[180px] overflow-auto p-3">
        <div class="mb-2 text-xs font-medium">{m.http_test_request_preview()}</div>
        <div class="space-y-2 font-mono text-xs">
          <div class="flex flex-wrap gap-2">
            <span>{result.request_preview.method}</span>
            <span class="break-all">{result.request_preview.url}</span>
          </div>
          {#if Object.keys(result.request_preview.headers).length > 0}
            <pre>{formatPreviewHeaders(result.request_preview)}</pre>
          {/if}
          {#if result.request_preview.body_preview}
            <pre>{result.request_preview.body_preview}</pre>
          {/if}
        </div>
      </Card.Content>
    </Card.Root>
  {/if}
  {#if result?.response_preview}
    <Card.Root>
      <Card.Content class="max-h-[120px] overflow-auto p-3">
        <div class="mb-2 text-xs font-medium">{m.http_test_response_preview()}</div>
        <pre class="font-mono text-xs">{result.response_preview}</pre>
      </Card.Content>
    </Card.Root>
  {/if}
</div>
