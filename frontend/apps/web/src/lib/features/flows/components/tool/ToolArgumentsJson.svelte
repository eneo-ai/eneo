<script lang="ts">
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import VariablePicker, {
    type VariablePickerContext
  } from "$lib/features/flows/components/VariablePicker.svelte";
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
    keptText = null,
    onUnsavedText,
    variableContext,
    reservedNames = [],
    label = m.flow_tool_arguments_title(),
    hint = m.flow_tool_arguments_json_hint()
  }: {
    /** The arguments this field edits, as stored. */
    value: JsonObject;
    disabled: boolean;
    onChange: (value: JsonObject) => void;
    /** Text typed here earlier that the step could not hold; shown in place of `value`. */
    keptText?: string | null;
    /** Called with the typed text the step cannot hold, or null once the text is stored. */
    onUnsavedText?: (text: string | null) => void;
    /** Offers the flow's variables, each put in as one whole JSON string at the cursor. */
    variableContext?: VariablePickerContext;
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

  // A stored text stays as typed while the step holds the arguments it gave;
  // once other arguments are stored it is dropped for good, so it does not
  // come back with the old ones. A text the step cannot hold is the editor's
  // draft (`keptText`), never kept here.
  let lastTyped: { text: string; stored: JsonObject } | null = null;
  let typed = $derived.by(() => {
    // Read first: the stored value is what this re-runs on, also while nothing is typed.
    const stored = value;
    if (lastTyped !== null && !sameJson(lastTyped.stored, stored)) lastTyped = null;
    return lastTyped;
  });
  const draft = $derived(keptText ?? typed?.text ?? JSON.stringify(value, null, 2));
  const result = $derived(read(draft));

  function type(text: string) {
    const next = read(text);
    onUnsavedText?.(next.ok ? null : text);
    if (!next.ok) return;
    typed = lastTyped = { text, stored: next.value };
    onChange(next.value);
  }

  let field = $state<HTMLTextAreaElement | null>(null);

  // An argument reads one whole variable, which in JSON is one string.
  // True while the last chosen variable could not go in at the cursor.
  let insertRefused = $state(false);

  // A variable goes in only where it leaves a JSON object; elsewhere the text
  // stays as it is and the author is told where to put the cursor.
  function insertVariable(variable: string) {
    const start = field?.selectionStart ?? draft.length;
    const end = field?.selectionEnd ?? start;
    const next = draft.slice(0, start) + JSON.stringify(variable) + draft.slice(end);
    const parsed = readJson(next);
    insertRefused = !parsed.ok || !isJsonObject(parsed.value);
    if (!insertRefused) type(next);
  }
</script>

<div class="flex flex-col gap-2" data-tool-arguments-json>
  <p id="{uid}-hint" class="text-secondary text-sm">{hint}</p>
  <Textarea
    bind:ref={field}
    class="min-h-[120px] font-mono text-xs"
    value={draft}
    {disabled}
    aria-label={label}
    aria-invalid={!result.ok || undefined}
    aria-describedby={result.ok ? `${uid}-hint` : `${uid}-hint ${uid}-error`}
    oninput={(event) => {
      insertRefused = false;
      type(event.currentTarget.value);
    }}
  />
  {#if !result.ok}
    <p id="{uid}-error" class="text-negative-stronger text-xs">{result.error}</p>
  {/if}
  {#if insertRefused}
    <p class="text-warning-stronger text-xs" role="status">
      {m.flow_tool_arguments_insert_where()}
    </p>
  {/if}
  {#if variableContext && !disabled}
    <div>
      <VariablePicker
        steps={variableContext.steps}
        currentStepOrder={variableContext.currentStepOrder}
        formSchema={variableContext.formSchema}
        isAdvancedMode={variableContext.isAdvancedMode}
        transcriptionEnabled={variableContext.transcriptionEnabled}
        triggerLabel={m.flow_tool_arguments_insert_variable()}
        allowFor="tool_argument"
        onInsert={insertVariable}
      />
    </div>
  {/if}
</div>
