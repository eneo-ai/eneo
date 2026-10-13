<script lang="ts">
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import { isJsonObject, type JsonObject } from "$lib/features/flows/jsonObject";
  import { m } from "$lib/paraglide/messages";
  import {
    boundVariableToken,
    holdsInexactNumber,
    holdsVariable,
    readJson,
    sameJson
  } from "./toolInputConfig";

  let {
    value,
    disabled,
    onChange,
    reservedNames = [],
    label = m.flow_tool_arguments_title(),
    hint = m.flow_tool_arguments_json_hint()
  }: {
    /** The arguments this field edits, as stored. */
    value: JsonObject;
    disabled: boolean;
    onChange: (value: JsonObject) => void;
    /** Arguments that have a field of their own elsewhere, which this field refuses. */
    reservedNames?: string[];
    label?: string;
    hint?: string;
  } = $props();

  const uid = $props.id();
  type Read = { ok: true; value: JsonObject } | { ok: false; error: string };

  /** The arguments a typed text gives, or why the step cannot hold them. */
  function read(text: string): Read {
    const parsed = readJson(text);
    if (!parsed.ok || !isJsonObject(parsed.value)) {
      return { ok: false, error: m.flow_tool_arguments_json_invalid() };
    }
    const reserved = Object.keys(parsed.value).find((argument) => reservedNames.includes(argument));
    if (reserved !== undefined) {
      return { ok: false, error: m.flow_tool_argument_has_own_field({ argument: reserved }) };
    }
    if (holdsInexactNumber(parsed.value)) {
      return { ok: false, error: m.flow_tool_argument_number_too_large() };
    }
    // An argument is a fixed value or one whole variable, as in a row.
    for (const [argument, stored] of Object.entries(parsed.value)) {
      if (boundVariableToken(stored) !== null || !holdsVariable(stored)) continue;
      return {
        ok: false,
        error:
          typeof stored === "string"
            ? m.flow_tool_argument_composed_text({ argument })
            : m.flow_tool_argument_nested_reference({ argument })
      };
    }
    return { ok: true, value: parsed.value };
  }

  // The text as typed stays while the step holds what the row stored for it;
  // arguments changed from outside are shown instead.
  let typed = $state<{ text: string; stored: JsonObject } | null>(null);
  const draft = $derived(
    typed !== null && sameJson(typed.stored, value) ? typed.text : JSON.stringify(value, null, 2)
  );
  const result = $derived(read(draft));

  function type(text: string) {
    const next = read(text);
    typed = { text, stored: next.ok ? next.value : value };
    if (next.ok) onChange(next.value);
  }
</script>

<div class="flex flex-col gap-2">
  <p id="{uid}-hint" class="text-secondary text-sm">{hint}</p>
  <Textarea
    class="min-h-[120px] font-mono text-xs"
    value={draft}
    {disabled}
    aria-label={label}
    aria-invalid={!result.ok || undefined}
    aria-describedby={result.ok ? `${uid}-hint` : `${uid}-hint ${uid}-error`}
    oninput={(event) => type(event.currentTarget.value)}
  />
  {#if !result.ok}
    <p id="{uid}-error" class="text-negative-stronger text-xs">{result.error}</p>
  {/if}
</div>
