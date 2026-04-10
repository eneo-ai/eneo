<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
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
      <select
        class="border-default bg-primary focus-within:border-accent-default focus-within:ring-accent-default/20 hover:border-stronger w-full rounded-xl border px-3.5 py-2.5 text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:ring-2 focus-visible:outline-none disabled:opacity-50"
        value={body.mode}
        disabled={isPublished}
        onchange={(e) => handleModeChange(e.currentTarget.value as HttpBodyMode)}
      >
        {#each BODY_MODES_POST as mode (mode.value)}
          <option value={mode.value}>{mode.label}</option>
        {/each}
      </select>

      {#if body.mode === "auto"}
        <p class="text-muted text-xs leading-relaxed">
          {m.http_body_auto_desc()}
        </p>
      {/if}

      {#if body.mode === "json_template" || body.mode === "text_template"}
        <textarea
          class="border-default bg-primary focus-within:border-accent-default focus-within:ring-accent-default/20 hover:border-stronger min-h-[120px] w-full rounded-lg border px-3 py-2 font-mono text-xs shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:ring-2 focus-visible:outline-none disabled:opacity-50 {isJsonInvalid
            ? 'border-danger-default/60'
            : ''}"
          value={body.template ?? ""}
          disabled={isPublished}
          placeholder={body.mode === "json_template"
            ? '{\n  "result": "{{ föregående_steg }}"\n}'
            : m.http_body_text_placeholder()}
          oninput={(e) => handleTemplateChange(e.currentTarget.value)}
        ></textarea>
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
