<script lang="ts">
  import FlowStepSection from "$lib/features/flows/components/FlowStepSection.svelte";
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import type {
    HttpAuthoredConfig,
    HttpDirection,
    HttpMethod,
    HttpAuth,
    HttpBody,
    CustomHeader
  } from "./httpConfigTypes";
  import HttpAuthSection from "./HttpAuthSection.svelte";
  import HttpHeadersEditor from "./HttpHeadersEditor.svelte";
  import HttpBodyEditor from "./HttpBodyEditor.svelte";
  import HttpTestConnection from "./HttpTestConnection.svelte";
  import * as Select from "$lib/components/ui/select/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { getAuthoredHttpUrlError } from "./httpConfigDefaults";

  let {
    config,
    direction,
    method,
    isPublished,
    flowId,
    onConfigChange
  }: {
    config: HttpAuthoredConfig;
    direction: HttpDirection;
    method: HttpMethod;
    isPublished: boolean;
    flowId: string;
    onConfigChange?: (detail: { config: HttpAuthoredConfig }) => void;
  } = $props();

  function update(patch: Partial<HttpAuthoredConfig>) {
    onConfigChange?.({ config: { ...config, ...patch } });
  }

  const urlInvalid = $derived(getAuthoredHttpUrlError(config.url) === "HTTP_INVALID_URL");
  const responseFormatValue = $derived(config.response_format ?? "text");
  const responseFormatLabel = $derived(
    responseFormatValue === "json" ? m.http_response_format_json() : m.http_response_format_text()
  );
</script>

<FlowStepSection title={m.http_config_title()}>
  <Settings.Row title={m.http_url_title()} description="">
    <div class="flex flex-col gap-1">
      <Input
        type="url"
        placeholder="https://api.example.com/webhook"
        value={config.url}
        disabled={isPublished}
        aria-invalid={urlInvalid || undefined}
        oninput={(e) => update({ url: e.currentTarget.value })}
      />
      {#if urlInvalid}
        <p class="text-danger-default text-xs">{m.http_url_invalid()}</p>
      {/if}
    </div>
  </Settings.Row>

  <HttpAuthSection
    auth={config.auth}
    {isPublished}
    onAuthChange={(detail) => update({ auth: detail.auth })}
  />

  <HttpBodyEditor
    body={config.body}
    {method}
    {isPublished}
    onBodyChange={(detail) => update({ body: detail.body })}
  />

  {#if direction === "input"}
    <Settings.Row title={m.http_response_format()} description="">
      <Select.Root
        type="single"
        value={responseFormatValue}
        disabled={isPublished}
        onValueChange={(value) => update({ response_format: value as "text" | "json" })}
      >
        <Select.Trigger class="w-full" aria-label={m.http_response_format()}>
          {responseFormatLabel}
        </Select.Trigger>
        <Select.Content>
          <Select.Group>
            <Select.Item value="text" label={m.http_response_format_text()}>
              {m.http_response_format_text()}
            </Select.Item>
            <Select.Item value="json" label={m.http_response_format_json()}>
              {m.http_response_format_json()}
            </Select.Item>
          </Select.Group>
        </Select.Content>
      </Select.Root>
    </Settings.Row>
  {/if}

  <HttpHeadersEditor
    headers={config.custom_headers}
    {isPublished}
    onHeadersChange={(detail) => update({ custom_headers: detail.headers })}
  />

  <Settings.Row title={m.http_timeout_title()} description="">
    <div class="flex items-center gap-2">
      <Input
        class="w-24"
        type="number"
        min="1"
        max="120"
        value={config.timeout_seconds}
        disabled={isPublished}
        oninput={(e) =>
          update({
            timeout_seconds: Math.max(1, Math.min(120, Number(e.currentTarget.value) || 30))
          })}
      />
      <span class="text-muted text-sm">{m.http_timeout_unit()}</span>
    </div>
  </Settings.Row>

  <Settings.Row title={m.http_test_title()} description="" fullWidth={true}>
    <HttpTestConnection {config} {direction} {method} {flowId} {isPublished} />
  </Settings.Row>
</FlowStepSection>
