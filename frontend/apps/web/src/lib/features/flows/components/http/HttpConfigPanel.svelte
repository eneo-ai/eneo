<script lang="ts">
  import FlowStepSection from "$lib/features/flows/components/FlowStepSection.svelte";
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import type { HttpAuthoredConfig, HttpDirection, HttpMethod } from "./httpConfigTypes";
  import HttpAuthSection from "./HttpAuthSection.svelte";
  import HttpHeadersEditor from "./HttpHeadersEditor.svelte";
  import HttpBodyEditor from "./HttpBodyEditor.svelte";
  import HttpTestConnection from "./HttpTestConnection.svelte";
  import * as Select from "$lib/components/ui/select/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import VariablePicker from "$lib/features/flows/components/VariablePicker.svelte";
  import { getAuthoredHttpUrlError } from "./httpConfigDefaults";
  import type { VariablePickerContext } from "$lib/features/flows/components/VariablePicker.svelte";

  let {
    config,
    direction,
    method,
    isPublished,
    flowId,
    variableContext,
    onConfigChange
  }: {
    config: HttpAuthoredConfig;
    direction: HttpDirection;
    method: HttpMethod;
    isPublished: boolean;
    flowId: string;
    variableContext?: VariablePickerContext;
    onConfigChange?: (detail: { config: HttpAuthoredConfig }) => void;
  } = $props();

  function update(patch: Partial<HttpAuthoredConfig>) {
    onConfigChange?.({ config: { ...config, ...patch } });
  }

  const uid = $props.id();

  const urlInvalid = $derived(getAuthoredHttpUrlError(config.url) === "HTTP_INVALID_URL");

  function clampTimeout(raw: string): number {
    return Math.max(1, Math.min(120, Number(raw) || 30));
  }

  function insertUrlVariable(variable: string) {
    const el = document.getElementById(`${uid}-url`);
    if (el instanceof HTMLInputElement) {
      const start = el.selectionStart ?? config.url.length;
      const end = el.selectionEnd ?? config.url.length;
      update({ url: config.url.slice(0, start) + variable + config.url.slice(end) });
    } else {
      update({ url: config.url + variable });
    }
  }
  const responseFormatValue = $derived(config.response_format ?? "text");
  const responseFormatLabel = $derived(
    responseFormatValue === "json" ? m.http_response_format_json() : m.http_response_format_text()
  );
</script>

<FlowStepSection title={m.http_config_title()}>
  <Settings.Row title={m.http_url_title()} description={m.http_url_desc()} density="compact">
    <div class="flex flex-col gap-1">
      <div class="flex items-center gap-2">
        <Input
          id="{uid}-url"
          class="flex-1"
          type="url"
          placeholder={m.http_url_placeholder()}
          aria-label={m.http_url_title()}
          value={config.url}
          disabled={isPublished}
          aria-invalid={urlInvalid || undefined}
          aria-describedby={urlInvalid ? `${uid}-url-error` : undefined}
          oninput={(e) => update({ url: e.currentTarget.value })}
        />
        {#if variableContext && !isPublished}
          <VariablePicker
            steps={variableContext.steps}
            currentStepOrder={variableContext.currentStepOrder}
            formSchema={variableContext.formSchema}
            isAdvancedMode={variableContext.isAdvancedMode}
            transcriptionEnabled={variableContext.transcriptionEnabled}
            onInsert={insertUrlVariable}
          />
        {/if}
      </div>
      {#if urlInvalid}
        <p id="{uid}-url-error" class="text-negative-stronger text-xs">{m.http_url_invalid()}</p>
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
    {variableContext}
    onBodyChange={(detail) => update({ body: detail.body })}
  />

  {#if direction === "input"}
    <Settings.Row
      title={m.http_response_format()}
      description={m.http_response_format_desc()}
      density="compact"
    >
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

  <Settings.Row
    title={m.http_timeout_title()}
    description={m.http_timeout_desc()}
    help={m.http_timeout_help()}
    density="compact"
  >
    <div class="flex items-center gap-2">
      <Input
        class="w-24"
        type="number"
        min="1"
        max="120"
        aria-label={m.http_timeout_title()}
        value={config.timeout_seconds}
        disabled={isPublished}
        oninput={(e) => {
          const raw = e.currentTarget.value;
          const parsed = Number(raw);
          if (raw !== "" && Number.isFinite(parsed) && parsed >= 1 && parsed <= 120) {
            update({ timeout_seconds: parsed });
          }
        }}
        onchange={(e) => {
          const clamped = clampTimeout(e.currentTarget.value);
          e.currentTarget.value = String(clamped);
          update({ timeout_seconds: clamped });
        }}
      />
      <span class="text-muted text-sm">{m.http_timeout_unit()}</span>
    </div>
  </Settings.Row>

  <Settings.Row
    title={m.http_test_title()}
    description={m.http_test_desc()}
    fullWidth={true}
    density="compact"
  >
    <HttpTestConnection {config} {direction} {method} {flowId} {isPublished} />
  </Settings.Row>
</FlowStepSection>
