<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import VariablePicker from "$lib/features/flows/components/VariablePicker.svelte";
  import type { HttpBody, HttpBodyMode, HttpMethod } from "./httpConfigTypes";
  import type { VariablePickerContext } from "$lib/features/flows/components/VariablePicker.svelte";

  let {
    body,
    method,
    isPublished,
    variableContext,
    onBodyChange
  }: {
    body: HttpBody;
    method: HttpMethod;
    isPublished: boolean;
    variableContext?: VariablePickerContext;
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

  const uid = $props.id();

  // The previous-step variable is a reserved runtime identifier, identical in
  // every locale; only the field-name example is localized.
  const jsonPlaceholder = `{\n  "${m.http_body_placeholder_field()}": "{{ föregående_steg }}"\n}`;
  const textPlaceholder = `${m.http_body_placeholder_greeting()} {{ ${m.http_body_placeholder_name()} }}!`;

  const canFormatJson = $derived.by(() => {
    if (body.mode !== "json_template") return false;
    if (body.template == null || body.template.trim().length === 0) return false;
    if (body.template.includes("{{")) return false;
    try {
      JSON.parse(body.template);
      return true;
    } catch {
      return false;
    }
  });

  function formatJson() {
    if (body.template == null) return;
    try {
      handleTemplateChange(JSON.stringify(JSON.parse(body.template), null, 2));
    } catch {
      // Leave the template untouched when it is not plain JSON.
    }
  }

  function insertVariable(variable: string) {
    const el = document.getElementById(`${uid}-template`);
    const current = body.template ?? "";
    if (el instanceof HTMLTextAreaElement) {
      const start = el.selectionStart ?? current.length;
      const end = el.selectionEnd ?? current.length;
      handleTemplateChange(current.slice(0, start) + variable + current.slice(end));
    } else {
      handleTemplateChange(current + variable);
    }
  }
</script>

{#if method === "POST"}
  <Settings.Row title={m.http_body_title()} description={m.http_body_desc()} density="compact">
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
        {#if !isPublished && (variableContext || body.mode === "json_template")}
          <div class="flex items-center justify-end gap-2">
            {#if body.mode === "json_template"}
              <Button variant="ghost" size="sm" disabled={!canFormatJson} onclick={formatJson}>
                {m.http_body_format_json()}
              </Button>
            {/if}
            {#if variableContext}
              <VariablePicker
                steps={variableContext.steps}
                currentStepOrder={variableContext.currentStepOrder}
                formSchema={variableContext.formSchema}
                isAdvancedMode={variableContext.isAdvancedMode}
                transcriptionEnabled={variableContext.transcriptionEnabled}
                onInsert={insertVariable}
              />
            {/if}
          </div>
        {/if}
        <Textarea
          id="{uid}-template"
          class="min-h-[120px] font-mono text-xs"
          aria-label={bodyModeLabel}
          aria-invalid={isJsonInvalid || undefined}
          aria-describedby={isJsonInvalid ? `${uid}-json-error` : undefined}
          value={body.template ?? ""}
          disabled={isPublished}
          placeholder={body.mode === "json_template" ? jsonPlaceholder : textPlaceholder}
          oninput={(e) => handleTemplateChange(e.currentTarget.value)}
        />
        {#if isJsonInvalid}
          <p id="{uid}-json-error" class="text-negative-stronger text-xs">
            {m.http_body_invalid_json()}
          </p>
        {/if}
        <p class="text-muted text-xs leading-relaxed">
          {m.http_body_template_hint()}
        </p>
      {/if}
    </div>
  </Settings.Row>
{/if}
