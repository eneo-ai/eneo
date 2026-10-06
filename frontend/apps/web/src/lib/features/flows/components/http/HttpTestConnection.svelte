<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { IconCheck } from "@eneo/icons/check";
  import { IconXMark } from "@eneo/icons/x-mark";
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
  import { getEneo } from "$lib/core/Eneo";
  import {
    describeFlowApiError,
    getFlowRuntimeErrorMessage
  } from "$lib/features/flows/flowRuntimeErrorMapping";

  let {
    config,
    direction,
    method,
    flowId,
    stepId,
    isPublished
  }: {
    config: HttpAuthoredConfig;
    direction: HttpDirection;
    method: HttpMethod;
    flowId: string;
    stepId?: string | null;
    isPublished: boolean;
  } = $props();

  const eneo = getEneo();
  let testing = $state(false);
  let testVariablesText = $state("{}");
  let result: FlowHttpTestResponse | null = $state(null);
  let localFailureMessage: string | null = $state(null);

  const errorMessages: Record<NonNullable<FlowHttpTestResponse["error_code"]>, () => string> = {
    HTTP_MISSING_URL: m.http_test_needs_url,
    HTTP_INVALID_URL: m.http_url_invalid,
    HTTP_VARIABLE_RESOLUTION_FAILED: m.http_test_variable_resolution_failed,
    HTTP_UNRESOLVED_STORED_SECRET: m.http_test_saved_secret_unavailable,
    HTTP_MISSING_AUTH: m.http_test_auth_missing,
    HTTP_INVALID_BODY_JSON: m.http_test_body_invalid,
    HTTP_BODY_NOT_ALLOWED_FOR_GET: m.http_test_body_not_allowed,
    HTTP_TIMEOUT_OUT_OF_RANGE: m.http_test_timeout_invalid,
    HTTP_TIMEOUT: m.flow_error_typed_io_http_timeout,
    HTTP_CONNECTION_REFUSED: m.flow_error_typed_io_http_connection_error,
    HTTP_BLOCKED_URL: m.flow_error_typed_io_http_ssrf_blocked,
    HTTP_RESPONSE_TOO_LARGE: m.flow_error_typed_io_http_response_too_large,
    HTTP_STATUS_ERROR: m.flow_error_typed_io_http_non_success,
    HTTP_CREDENTIALS_REQUIRE_HTTPS: m.http_test_credentials_require_https
  };

  const hasTemplateMarkers = $derived.by(() => JSON.stringify(config).includes("{{"));

  async function runTest() {
    if (!stepId || !config.url.trim()) return;

    const parsedVariables = hasTemplateMarkers
      ? parseHttpTestVariables(testVariablesText)
      : { ok: true as const, value: {} };
    if (!parsedVariables.ok) {
      result = localError(m.http_test_variables_invalid());
      return;
    }

    testing = true;
    result = null;
    localFailureMessage = null;

    try {
      const body: FlowHttpTestRequest = {
        step_id: stepId,
        config,
        direction,
        method,
        test_variables: parsedVariables.value
      };
      result = await eneo.flows.httpTest({ id: flowId, request: body });
    } catch (err) {
      const fallback = m.http_test_unknown_error();
      result = localError(
        describeFlowApiError(err) ? getFlowRuntimeErrorMessage(err, fallback) : fallback
      );
    } finally {
      testing = false;
    }
  }

  function localError(message: string): FlowHttpTestResponse {
    localFailureMessage = message;
    return { success: false };
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
        placeholder={'{ "base_url": "https://api.example.com" }'}
        oninput={(e) => (testVariablesText = e.currentTarget.value)}
      />
      <span class="text-muted text-xs leading-relaxed">{m.http_test_variables_help()}</span>
    </label>
  {/if}

  <div class="flex flex-wrap items-center gap-3">
    <Button
      variant="outline"
      size="sm"
      disabled={isPublished || testing || !stepId || !config.url.trim()}
      onclick={runTest}
    >
      {#if testing}
        {m.http_test_testing()}
      {:else}
        {m.http_test_button()}
      {/if}
    </Button>
    {#if !isPublished && !config.url.trim()}
      <span class="text-muted text-xs">{m.http_test_needs_url()}</span>
    {:else if !isPublished && !stepId}
      <span class="text-muted text-xs">{m.http_test_saved_step_required()}</span>
    {/if}
    <div role="status" aria-live="polite" class="min-w-0">
      {#if result}
        <span
          class="flex items-center gap-1.5 text-xs font-medium {result.success
            ? 'text-accent-default'
            : 'text-negative-stronger'}"
        >
          {#if result.success}
            <IconCheck class="size-3.5 shrink-0" />
            {m.http_test_success()}
          {:else}
            <IconXMark class="size-3.5 shrink-0" />
            <span class="min-w-0 break-words">
              {m.http_test_failed_prefix()}: {localFailureMessage ??
                (result.error_code ? errorMessages[result.error_code]?.() : null) ??
                m.http_test_unknown_error()}
            </span>
          {/if}
          {#if result.status_code != null}
            <span class="shrink-0">
              ({result.status_code}{#if result.duration_ms != null},
                {Math.round(result.duration_ms)}&nbsp;ms{/if})
            </span>
          {/if}
        </span>
      {/if}
    </div>
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
