<script lang="ts">
  import { untrack } from "svelte";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import * as ToggleGroup from "$lib/components/ui/toggle-group/index.js";
  import VariablePicker, {
    type VariablePickerContext
  } from "$lib/features/flows/components/VariablePicker.svelte";
  import { DELETED_STEP_TOKEN } from "$lib/features/flows/flowStepConfigValidation";
  import { m } from "$lib/paraglide/messages";
  import {
    boundVariableToken,
    holdsInexactNumber,
    holdsVariable,
    readJson,
    sameJson
  } from "./toolInputConfig";
  import {
    isRequiredArgumentMissing,
    type ToolArgumentControl,
    type ToolArgumentField
  } from "./toolInputSchema";

  type Mode = "fixed" | "variable" | "unset";
  type FixedRead = { ok: true; value: unknown } | { ok: false; error: string | null };

  let {
    field,
    value,
    disabled,
    variableContext,
    onChange
  }: {
    field: ToolArgumentField;
    /** The stored value; undefined while the argument is absent. */
    value: unknown;
    disabled: boolean;
    variableContext?: VariablePickerContext;
    /** Called with the value to store, or undefined to leave the argument out. */
    onChange: (value: unknown) => void;
  } = $props();

  const uid = $props.id();
  const control = $derived(field.control);
  const token = $derived(boundVariableToken(value));

  function fits(shown: ToolArgumentControl, stored: unknown): boolean {
    switch (shown.kind) {
      case "text":
        return typeof stored === "string";
      case "number":
        return typeof stored === "number" && (!shown.integer || Number.isInteger(stored));
      case "boolean":
        return typeof stored === "boolean";
      case "choice":
        return shown.options.some((option) => option === stored);
      case "json":
        return true;
    }
  }

  // An argument without a value is a fixed value still to enter, a variable
  // still to choose, or not set. The step holds nothing that tells them apart,
  // so the row remembers which the author chose.
  let emptyMode = $state<Mode>(untrack(() => (field.required ? "fixed" : "unset")));
  const mode = $derived.by((): Mode => {
    if (value !== undefined) return token !== null ? "variable" : "fixed";
    return field.required && emptyMode === "unset" ? "fixed" : emptyMode;
  });
  // A stored fixed value the tool no longer takes: the row asks for it again.
  const misfit = $derived(mode === "fixed" && value !== undefined && !fits(control, value));

  // The text the author typed in this row, with the value the row stored for
  // it. While the step still holds that value the row shows the text as typed;
  // any other stored value came from outside the row and is shown instead.
  let typed = $state<{ text: string; stored: unknown } | null>(null);
  const draft = $derived.by((): string => {
    if (typed !== null && sameJson(typed.stored, value)) return typed.text;
    if (value === undefined || token !== null || misfit) return "";
    if (control.kind === "json") return JSON.stringify(value, null, 2);
    return control.kind === "text" || control.kind === "number" ? String(value) : "";
  });

  function refused(error: string | null): FixedRead {
    return { ok: false, error };
  }

  /** What a typed text is for this control: the value to store, or why it is not stored. */
  function readFixed(text: string): FixedRead {
    switch (control.kind) {
      case "text":
        // An empty text is a value too; "Not set" leaves the argument out.
        return holdsVariable(text)
          ? refused(m.flow_tool_argument_fixed_has_variable())
          : { ok: true, value: text };
      case "number": {
        if (text.trim() === "") return refused(null);
        const number = Number(text);
        if (Number.isNaN(number)) return refused(null);
        if (holdsInexactNumber(number)) return refused(m.flow_tool_argument_number_too_large());
        if (control.integer && !Number.isInteger(number)) {
          return refused(m.flow_tool_argument_not_integer());
        }
        return { ok: true, value: number };
      }
      case "json": {
        if (text.trim() === "") return refused(null);
        const parsed = readJson(text);
        if (!parsed.ok) return refused(m.flow_tool_argument_json_invalid());
        if (holdsInexactNumber(parsed.value)) {
          return refused(m.flow_tool_argument_number_too_large());
        }
        if (typeof parsed.value === "string" && holdsVariable(parsed.value)) {
          return refused(m.flow_tool_argument_fixed_has_variable());
        }
        return holdsVariable(parsed.value)
          ? refused(m.flow_tool_argument_nested_reference({ argument: field.name }))
          : { ok: true, value: parsed.value };
      }
      default:
        return refused(null);
    }
  }

  const error = $derived.by((): string | null => {
    if (typeof value === "string" && DELETED_STEP_TOKEN.test(value)) {
      return m.flow_template_issue_deleted_step();
    }
    const read = mode === "fixed" ? readFixed(draft) : null;
    if (read && !read.ok && read.error !== null) return read.error;
    return isRequiredArgumentMissing(field, value)
      ? m.flow_tool_argument_missing({ name: field.name })
      : null;
  });

  function chooseMode(next: string) {
    // Pressing the chosen kind again would clear the group; one is always chosen.
    if (next !== "fixed" && next !== "variable" && next !== "unset") return;
    if (next === mode) return;
    emptyMode = next;
    typed = null;
    onChange(undefined);
  }

  function typeFixed(text: string) {
    const read = readFixed(text);
    typed = { text, stored: read.ok ? read.value : undefined };
    emptyMode = "fixed";
    onChange(typed.stored);
  }

  // A switch always shows yes or no, so a yes/no argument that is fixed and
  // has no value is stored as the "no" the switch shows.
  $effect(() => {
    if (!disabled && mode === "fixed" && control.kind === "boolean" && value === undefined) {
      onChange(false);
    }
  });

  const invalid = $derived(error !== null || undefined);
  const emptyText = $derived(mode === "fixed" && control.kind === "text" && value === "");
  const describedBy = $derived(
    [
      field.description ? `${uid}-help` : null,
      misfit ? `${uid}-misfit` : null,
      error ? `${uid}-error` : null,
      emptyText ? `${uid}-empty` : null
    ]
      .filter((id) => id !== null)
      .join(" ") || undefined
  );
  const valueLabel = $derived(m.flow_tool_argument_value_label({ argument: field.name }));
</script>

<div
  role="group"
  aria-labelledby="{uid}-name"
  class="border-default flex flex-col gap-2 rounded-lg border px-3 py-3"
>
  <div class="flex flex-wrap items-center gap-2">
    <code
      id="{uid}-name"
      translate="no"
      class="text-primary min-w-0 font-mono text-sm font-medium break-all">{field.name}</code
    >
    {#if field.required}
      <Badge variant="outline">{m.flow_tool_argument_required()}</Badge>
    {/if}
  </div>
  {#if field.description}
    <p id="{uid}-help" class="text-muted text-xs leading-relaxed">{field.description}</p>
  {/if}

  <ToggleGroup.Root
    type="single"
    variant="outline"
    size="sm"
    spacing={0}
    {disabled}
    bind:value={() => mode, chooseMode}
    aria-label={m.flow_tool_argument_mode_label({ argument: field.name })}
  >
    <ToggleGroup.Item value="fixed">{m.flow_tool_argument_mode_fixed()}</ToggleGroup.Item>
    <ToggleGroup.Item value="variable">{m.flow_tool_argument_mode_variable()}</ToggleGroup.Item>
    {#if !field.required}
      <ToggleGroup.Item value="unset">{m.flow_tool_argument_mode_unset()}</ToggleGroup.Item>
    {/if}
  </ToggleGroup.Root>

  {#if mode === "variable"}
    <div class="flex flex-wrap items-center gap-2">
      {#if token}
        <code
          translate="no"
          class="bg-secondary text-primary max-w-full truncate rounded-md px-1.5 py-0.5 font-mono text-xs"
          >{`{{${token}}}`}</code
        >
      {/if}
      {#if variableContext && !disabled}
        <VariablePicker
          steps={variableContext.steps}
          currentStepOrder={variableContext.currentStepOrder}
          formSchema={variableContext.formSchema}
          isAdvancedMode={variableContext.isAdvancedMode}
          transcriptionEnabled={variableContext.transcriptionEnabled}
          triggerLabel={token
            ? m.flow_tool_argument_change_variable()
            : m.flow_tool_argument_choose_variable()}
          allowFor="tool_argument"
          onInsert={onChange}
        />
      {/if}
    </div>
    {#if !token}
      <p class="text-muted text-xs">{m.flow_tool_argument_variable_missing()}</p>
    {/if}
  {:else if mode === "fixed"}
    {#if control.kind === "text"}
      <Input
        type="text"
        value={draft}
        {disabled}
        aria-label={valueLabel}
        aria-invalid={invalid}
        aria-describedby={describedBy}
        oninput={(event) => typeFixed(event.currentTarget.value)}
      />
      {#if emptyText}
        <p id="{uid}-empty" class="text-muted text-xs">
          {m.flow_tool_argument_empty_text()}
          {#if !field.required}{m.flow_tool_argument_empty_text_unset()}{/if}
        </p>
      {/if}
    {:else if control.kind === "number"}
      <Input
        class="w-40"
        type="number"
        step={control.integer ? "1" : "any"}
        value={draft}
        {disabled}
        aria-label={valueLabel}
        aria-invalid={invalid}
        aria-describedby={describedBy}
        oninput={(event) => typeFixed(event.currentTarget.value)}
      />
    {:else if control.kind === "boolean"}
      <div class="flex items-center gap-2">
        <Switch
          checked={value === true}
          {disabled}
          aria-label={valueLabel}
          aria-invalid={invalid}
          aria-describedby={describedBy}
          onCheckedChange={onChange}
        />
        <span class="text-secondary text-sm">{value === true ? m.yes() : m.no()}</span>
      </div>
    {:else if control.kind === "choice"}
      {@const options = control.options}
      {@const chosen = options.findIndex((option) => option === value)}
      <Select.Root
        type="single"
        value={chosen === -1 ? "" : String(chosen)}
        {disabled}
        onValueChange={(index) => onChange(options[Number(index)])}
      >
        <Select.Trigger
          class="w-full"
          aria-label={valueLabel}
          aria-invalid={invalid}
          aria-describedby={describedBy}
        >
          {chosen === -1 ? m.flow_tool_argument_choice_placeholder() : String(value)}
        </Select.Trigger>
        <Select.Content>
          <Select.Group>
            {#each options as option, index (index)}
              <Select.Item value={String(index)} label={String(option)}>
                {String(option)}
              </Select.Item>
            {/each}
          </Select.Group>
        </Select.Content>
      </Select.Root>
    {:else}
      <Textarea
        class="min-h-[88px] font-mono text-xs"
        value={draft}
        {disabled}
        aria-label={valueLabel}
        aria-invalid={invalid}
        aria-describedby={describedBy}
        oninput={(event) => typeFixed(event.currentTarget.value)}
      />
    {/if}
    {#if misfit}
      <p id="{uid}-misfit" class="text-warning-stronger text-xs leading-relaxed">
        {m.flow_tool_argument_misfit()}
        <code translate="no" class="font-mono break-all">{JSON.stringify(value)}</code>
      </p>
    {/if}
  {/if}

  {#if error}
    <p id="{uid}-error" class="text-negative-stronger text-xs">{error}</p>
  {/if}
</div>
