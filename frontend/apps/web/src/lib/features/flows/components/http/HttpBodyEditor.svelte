<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import * as Select from "$lib/components/ui/select/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import type { HttpBody, HttpBodyMode, HttpMethod } from "./httpConfigTypes";

  let {
    body,
    method,
    isPublished,
    onBodyChange
  }: {
    body: HttpBody;
    method: HttpMethod;
    isPublished: boolean;
    onBodyChange?: (detail: { body: HttpBody }) => void;
  } = $props();

  const BODY_MODES_POST: Array<{ value: HttpBodyMode; label: string }> = [
    { value: "auto", label: m.http_body_auto() },
    { value: "json_template", label: m.http_body_json_template() },
    { value: "text_template", label: m.http_body_text_template() },
    { value: "none", label: m.http_body_none() }
  ];

  function handleModeChange(mode: HttpBodyMode) {
    onBodyChange?.({
      body: { mode, template: mode === "auto" || mode === "none" ? null : (body.template ?? "") }
    });
  }

  function handleTemplateChange(template: string) {
    onBodyChange?.({ body: { ...body, template } });
  }

  const bodyModeLabel = $derived(
    BODY_MODES_POST.find((mode) => mode.value === body.mode)?.label ?? body.mode
  );

  const isJsonInvalid = $derived.by(() => {
    if (body.mode !== "json_template") return false;
    if (body.template == null || body.template.trim().length === 0) return false;
    if (body.template.includes("{{")) return false;
    try {
      JSON.parse(body.template);
      return false;
    } catch {
      return true;
    }
  });
</script>

{#if method === "POST"}
  <Settings.Row title={m.http_body_title()} description="">
    <div class="flex flex-col gap-3">
      <Select.Root
        type="single"
        value={body.mode}
        disabled={isPublished}
        onValueChange={(value) => handleModeChange(value as HttpBodyMode)}
      >
        <Select.Trigger class="w-full" aria-label={m.http_body_title()}>
          {bodyModeLabel}
        </Select.Trigger>
        <Select.Content>
          <Select.Group>
            {#each BODY_MODES_POST as mode (mode.value)}
              <Select.Item value={mode.value} label={mode.label}>{mode.label}</Select.Item>
            {/each}
          </Select.Group>
        </Select.Content>
      </Select.Root>

      {#if body.mode === "auto"}
        <p class="text-muted text-xs leading-relaxed">
          {m.http_body_auto_desc()}
        </p>
      {/if}

      {#if body.mode === "json_template" || body.mode === "text_template"}
        <Textarea
          class="min-h-[120px] font-mono text-xs"
          aria-invalid={isJsonInvalid || undefined}
          value={body.template ?? ""}
          disabled={isPublished}
          placeholder={body.mode === "json_template"
            ? '{\n  "result": "{{ föregående_steg }}"\n}'
            : m.http_body_text_placeholder()}
          oninput={(e) => handleTemplateChange(e.currentTarget.value)}
        />
        {#if isJsonInvalid}
          <p class="text-danger-default text-xs">{m.http_body_invalid_json()}</p>
        {/if}
        <p class="text-muted text-xs leading-relaxed">
          {m.http_body_template_hint()}
        </p>
      {/if}
    </div>
  </Settings.Row>
{/if}
