<script lang="ts">
  import type { FlowStep } from "@intric/intric-js";
  import { createEventDispatcher, onDestroy, onMount, tick } from "svelte";
  import { m } from "$lib/paraglide/messages";
  import { isFlowFormFieldNameUsableAsVariable } from "$lib/features/flows/flowFormSchema";
  import {
    getChipClasses,
    parsePromptSegments,
    collectUnresolvedTemplateTokens,
    collectInvalidStructuredOutputReferences,
    type VariableCategory,
    type VariableClassificationContext,
  } from "$lib/features/flows/flowVariableTokens";
  import VariablePicker from "./VariablePicker.svelte";

  export let value: string;
  let currentEditorValue = value;
  let lastCommittedValue = value;
  let lastSeenPropValue = value;
  $: {
    if (value !== lastSeenPropValue) {
      const isLocalEcho = value === currentEditorValue;
      lastSeenPropValue = value;
      if (!isLocalEcho) {
        currentEditorValue = value;
        lastCommittedValue = value;
      }
    }
  }
  export let disabled: boolean = false;
  export let placeholder: string = "";
  export let label: string = m.flow_step_prompt();
  export let minHeight: number = 160;
  export let steps: FlowStep[];
  export let currentStepOrder: number;
  export let formSchema: { fields: { name: string; type: string; required?: boolean; options?: string[]; order?: number }[] } | undefined;
  export let transcriptionEnabled: boolean;
  export let isAdvancedMode: boolean = false;

  const dispatch = createEventDispatcher<{ change: string; commit: string }>();

  onMount(() => {
    // Initial auto-resize after first render
    tick().then(() => autoResize());
  });

  onDestroy(() => {
    commitIfDirty(currentEditorValue);
  });

  let textareaEl: HTMLTextAreaElement | null = null;
  let mirrorEl: HTMLDivElement | null = null;
  let autocompleteOpen = false;
  let autocompleteQuery = "";
  let selectedSuggestionIndex = 0;

  // Build classification context
  $: classificationContext = buildContext(steps, formSchema, transcriptionEnabled, currentStepOrder);

  function buildContext(
    steps: FlowStep[],
    formSchema: { fields: { name: string; type: string; required?: boolean; options?: string[]; order?: number }[] } | undefined,
    transcriptionEnabled: boolean,
    currentStepOrder: number,
  ): VariableClassificationContext {
    const knownFieldNames = new Set<string>();
    for (const field of formSchema?.fields ?? []) {
      const name = (field.name ?? "").trim();
      if (isFlowFormFieldNameUsableAsVariable(name)) knownFieldNames.add(name);
    }
    const knownStepNames = new Map<number, string>();
    const stepOutputTypes = new Map<number, string>();
    for (const step of steps) {
      const name = (step.user_description ?? "").trim();
      if (name) knownStepNames.set(step.step_order, name);
      stepOutputTypes.set(step.step_order, step.output_type);
    }
    return { knownFieldNames, knownStepNames, stepOutputTypes, transcriptionEnabled, currentStepOrder };
  }

  // Parse segments for mirror rendering
  $: segments = parsePromptSegments(currentEditorValue, classificationContext);

  // Available variables for chip bar and autocomplete
  $: availableVariables = buildAvailableVariables(classificationContext, steps, isAdvancedMode);

  type VariableSuggestion = {
    token: string;
    label: string;
    description: string;
    category: VariableCategory;
  };

  function buildAvailableVariables(
    ctx: VariableClassificationContext,
    steps: FlowStep[],
    showTechnical: boolean,
  ): VariableSuggestion[] {
    const suggestions: VariableSuggestion[] = [];

    // Form fields
    for (const name of ctx.knownFieldNames) {
      suggestions.push({ token: name, label: name, description: m.flow_variable_form_field(), category: "field" });
    }

    // System
    if (ctx.transcriptionEnabled) {
      suggestions.push({ token: "transkribering", label: "transkribering", description: m.flow_variable_transcription(), category: "system" });
    }
    if (showTechnical && ctx.currentStepOrder > 1) {
      suggestions.push({ token: "föregående_steg", label: "föregående_steg", description: m.flow_variable_previous_step(), category: "system" });
    }

    // Previous step name aliases
    for (const [order, name] of ctx.knownStepNames) {
      if (order < ctx.currentStepOrder && name) {
        suggestions.push({ token: name, label: name, description: m.flow_variable_step_alias({ order: String(order) }), category: "step" });
      }
    }

    // Technical (only in advanced mode)
    if (showTechnical) {
      const previousSteps = steps.filter((s) => s.step_order < ctx.currentStepOrder);
      for (const step of previousSteps) {
        suggestions.push({
          token: `step_${step.step_order}.output.text`,
          label: `step_${step.step_order}.output.text`,
          description: m.flow_variable_text_output(),
          category: "step",
        });
      }
    }

    return suggestions;
  }

  // Chip bar variables (filtered in user mode)
  $: chipBarVariables = isAdvancedMode ? availableVariables : availableVariables.filter(v => v.category === "field" || v.category === "step");

  // Unresolved count
  $: unresolvedCount = collectUnresolvedTemplateTokens(
    currentEditorValue,
    new Set(availableVariables.map((v) => v.token)),
  ).length;
  $: invalidStructuredReferences = collectInvalidStructuredOutputReferences(
    currentEditorValue,
    steps,
    currentStepOrder,
  );

  // Filtered suggestions for autocomplete
  $: filteredSuggestions = autocompleteQuery
    ? availableVariables.filter((v) =>
        v.label.toLowerCase().includes(autocompleteQuery.trim().toLowerCase()),
      )
    : availableVariables;

  // Scroll sync
  function syncScroll() {
    if (mirrorEl && textareaEl) {
      mirrorEl.scrollTop = textareaEl.scrollTop;
    }
  }

  // Char width measurement for autocomplete X positioning
  let charWidthCache = 0;
  function getCharWidth(): number {
    if (charWidthCache > 0) return charWidthCache;
    if (!textareaEl) return 8;
    const span = document.createElement("span");
    const computed = getComputedStyle(textareaEl);
    span.style.font = computed.font;
    span.style.position = "absolute";
    span.style.visibility = "hidden";
    span.textContent = "M";
    document.body.appendChild(span);
    charWidthCache = span.getBoundingClientRect().width;
    document.body.removeChild(span);
    return charWidthCache || 8;
  }

  // Auto-resize textarea to fit content
  function autoResize() {
    if (!textareaEl) return;
    textareaEl.style.height = "auto";
    textareaEl.style.height = textareaEl.scrollHeight + "px";
  }

  function handleInput(e: Event) {
    const target = e.target as HTMLTextAreaElement;
    currentEditorValue = target.value;
    dispatch("change", target.value);
    updateAutocompleteState();
    autoResize();
  }

  function findOpenTokenStart(text: string, cursorIndex: number): number | null {
    const beforeCursor = text.slice(0, cursorIndex);
    const openIndex = beforeCursor.lastIndexOf("{{");
    if (openIndex < 0) return null;
    const closingIndex = beforeCursor.lastIndexOf("}}");
    if (closingIndex > openIndex) return null;
    return openIndex;
  }

  function updateAutocompleteState() {
    if (!textareaEl) {
      autocompleteOpen = false;
      autocompleteQuery = "";
      return;
    }
    const cursor = textareaEl.selectionStart ?? currentEditorValue.length;
    const openIndex = findOpenTokenStart(currentEditorValue, cursor);
    if (openIndex === null) {
      autocompleteOpen = false;
      autocompleteQuery = "";
      return;
    }
    autocompleteOpen = true;
    autocompleteQuery = currentEditorValue.slice(openIndex + 2, cursor).trimStart();
    selectedSuggestionIndex = 0;
  }

  function handleKeydown(e: KeyboardEvent) {
    if ((e.metaKey || e.ctrlKey) && e.key === "s") {
      e.preventDefault();
      commitNow(currentEditorValue);
      return;
    }
    if (!autocompleteOpen || filteredSuggestions.length === 0) return;

    if (e.key === "ArrowDown") {
      e.preventDefault();
      selectedSuggestionIndex = (selectedSuggestionIndex + 1) % filteredSuggestions.length;
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      selectedSuggestionIndex = (selectedSuggestionIndex - 1 + filteredSuggestions.length) % filteredSuggestions.length;
    } else if (e.key === "Enter" || e.key === "Tab") {
      if (autocompleteOpen && filteredSuggestions.length > 0) {
        e.preventDefault();
        void applySuggestion(filteredSuggestions[selectedSuggestionIndex]);
      }
    } else if (e.key === "Escape") {
      autocompleteOpen = false;
      autocompleteQuery = "";
    }
  }

  async function applySuggestion(suggestion: VariableSuggestion) {
    const token = `{{${suggestion.token}}}`;
    if (!textareaEl) return;

    const cursor = textareaEl.selectionStart ?? currentEditorValue.length;
    const openIndex = findOpenTokenStart(currentEditorValue, cursor);

    if (openIndex !== null) {
      const nextText = currentEditorValue.slice(0, openIndex) + token + currentEditorValue.slice(cursor);
      currentEditorValue = nextText;
      dispatch("change", nextText);
      commitNow(nextText);
      await tick();
      if (textareaEl) {
        const nextCursor = openIndex + token.length;
        textareaEl.focus();
        textareaEl.setSelectionRange(nextCursor, nextCursor);
      }
    } else {
      void insertAtCursor(suggestion.token);
    }

    autocompleteOpen = false;
    autocompleteQuery = "";
    autoResize();
  }

  async function insertAtCursor(variableToken: string) {
    const token = `{{${variableToken}}}`;
    if (!textareaEl) {
      const nextText = `${currentEditorValue}${token}`;
      currentEditorValue = nextText;
      dispatch("change", nextText);
      commitNow(nextText);
      return;
    }
    const start = textareaEl.selectionStart ?? currentEditorValue.length;
    const end = textareaEl.selectionEnd ?? currentEditorValue.length;
    const nextText = currentEditorValue.slice(0, start) + token + currentEditorValue.slice(end);
    currentEditorValue = nextText;
    dispatch("change", nextText);
    commitNow(nextText);
    await tick();
    if (textareaEl) {
      const nextCursor = start + token.length;
      textareaEl.focus();
      textareaEl.setSelectionRange(nextCursor, nextCursor);
    }
  }

  // Autocomplete position (both X and Y)
  $: autocompletePosition = (() => {
    if (!textareaEl || !autocompleteOpen) return { top: 0, left: 16 };
    const cursor = textareaEl.selectionStart ?? 0;
    const textBeforeCursor = currentEditorValue.slice(0, cursor);
    const lineCount = (textBeforeCursor.match(/\n/g) ?? []).length;

    const computed = getComputedStyle(textareaEl);
    const lineHeight = parseFloat(computed.lineHeight) || 24;
    const paddingTop = parseFloat(computed.paddingTop) || 12;

    // Y: account for scroll position
    const rawTop = paddingTop + (lineCount + 1) * lineHeight;
    const top = Math.min(rawTop - textareaEl.scrollTop, textareaEl.clientHeight);

    // X: characters on current line × char width
    const lastNewline = textBeforeCursor.lastIndexOf("\n");
    const charsOnLine = lastNewline >= 0 ? cursor - lastNewline - 1 : cursor;
    const charWidth = getCharWidth();
    const paddingLeft = parseFloat(computed.paddingLeft) || 16;
    const rawLeft = paddingLeft + charsOnLine * charWidth;
    const maxLeft = textareaEl.clientWidth - 288; // 288px = w-72 dropdown width
    const left = Math.max(8, Math.min(rawLeft, maxLeft > 8 ? maxLeft : 8));

    return { top, left };
  })();

  function commitIfDirty(val: string) {
    if (val === lastCommittedValue) return;
    commitNow(val);
  }

  function commitNow(val: string) {
    lastCommittedValue = val;
    dispatch("commit", val);
  }
</script>

<div class="flow-prompt-editor border-default rounded-lg border shadow-sm transition-shadow focus-within:ring-2 focus-within:ring-accent-default/30">
  <!-- Toolbar -->
  <div class="flex items-center justify-between border-b border-default bg-secondary/30 px-3 py-1.5">
    <span class="text-[11px] text-muted">{label}</span>
    <div class="flex items-center gap-1">
      <slot name="toolbar" />
      {#if !disabled}
        <VariablePicker
          {steps}
          {currentStepOrder}
          {formSchema}
          {isAdvancedMode}
          {transcriptionEnabled}
          on:insert={(e) => {
            // e.detail is "{{token}}", extract the inner token
            const match = e.detail.match(/^\{\{(.+)\}\}$/);
            if (match) void insertAtCursor(match[1]);
          }}
        />
      {/if}
    </div>
  </div>

  <!-- Editor area (overlay pattern) -->
  <div class="relative" style={`min-height: ${minHeight}px`}>
    <!-- Mirror layer (behind, shows colored chips) -->
    <div
      aria-hidden="true"
      class="pointer-events-none absolute inset-0 overflow-hidden whitespace-pre-wrap break-words px-4 py-3 font-mono text-sm leading-relaxed"
      bind:this={mirrorEl}
    >
      {#each segments as seg, index (`${seg.type}:${seg.value}:${index}`)}
        {#if seg.type === "text"}<span class="text-primary">{seg.value}</span>{:else}<span class="{getChipClasses(seg.category)} inline">{seg.value}</span>{/if}
      {/each}
      <span>&nbsp;</span>
    </div>

    <!-- Textarea layer (on top, transparent text, visible caret) -->
    <textarea
      bind:this={textareaEl}
      class="relative z-10 w-full overflow-hidden bg-transparent px-4 py-3 font-mono text-sm leading-relaxed text-transparent caret-gray-900 dark:caret-gray-100 selection:bg-accent-dimmer selection:text-primary focus:outline-none"
      style={`min-height: ${minHeight}px`}
      on:input={handleInput}
      on:keydown={handleKeydown}
      on:scroll={syncScroll}
      on:click={updateAutocompleteState}
      on:keyup={updateAutocompleteState}
      on:blur={() => commitIfDirty(currentEditorValue)}
      {value}
      {disabled}
      {placeholder}
    ></textarea>

    <!-- Autocomplete dropdown -->
    {#if autocompleteOpen && filteredSuggestions.length > 0 && !disabled}
      <div
        class="absolute z-20 mt-1 max-h-48 w-72 overflow-y-auto rounded-lg border border-default bg-primary shadow-lg"
        style="top: {autocompletePosition.top}px; left: {autocompletePosition.left}px"
      >
        {#each filteredSuggestions as suggestion, i (suggestion.token)}
          <button
            type="button"
            class="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-hover-dimmer"
            class:bg-hover-dimmer={i === selectedSuggestionIndex}
            on:click={() => void applySuggestion(suggestion)}
          >
            <span class="{getChipClasses(suggestion.category)}">{suggestion.label}</span>
            <span class="text-[10px] text-muted">{suggestion.description}</span>
          </button>
        {/each}
      </div>
    {/if}
  </div>

  <!-- Quick-insert chip bar -->
  {#if chipBarVariables.length > 0 && !disabled}
    <div class="flex flex-wrap gap-1.5 border-t border-default bg-secondary/20 px-3 py-2">
      {#each chipBarVariables as v (v.token)}
        <button
          type="button"
          class="{getChipClasses(v.category)} cursor-pointer transition-all hover:scale-105 hover:shadow-sm active:scale-95"
          on:click={() => void insertAtCursor(v.token)}
        >
          {`{{${v.label}}}`}
        </button>
      {/each}
    </div>
  {/if}

  <!-- Unresolved variables warning -->
  {#if unresolvedCount > 0}
    <div class="flex items-center gap-2 border-t border-warning-default/40 bg-warning-dimmer px-3 py-1.5 text-xs text-warning-stronger">
      <svg class="size-3.5 shrink-0" viewBox="0 0 16 16" fill="currentColor">
        <path d="M8.982 1.566a1.13 1.13 0 0 0-1.96 0L.165 13.233c-.457.778.091 1.767.98 1.767h13.713c.889 0 1.438-.99.98-1.767L8.982 1.566zM8 5c.535 0 .954.462.9.995l-.35 3.507a.552.552 0 0 1-1.1 0L7.1 5.995A.905.905 0 0 1 8 5zm.002 6a1 1 0 1 1 0 2 1 1 0 0 1 0-2z"/>
      </svg>
      {unresolvedCount} {m.flow_prompt_unresolved_variables()}
    </div>
  {/if}

  {#if invalidStructuredReferences.length > 0}
    <div class="flex items-center gap-2 border-t border-warning-default/40 bg-warning-dimmer px-3 py-1.5 text-xs text-warning-stronger">
      <svg class="size-3.5 shrink-0" viewBox="0 0 16 16" fill="currentColor">
        <path d="M8.982 1.566a1.13 1.13 0 0 0-1.96 0L.165 13.233c-.457.778.091 1.767.98 1.767h13.713c.889 0 1.438-.99.98-1.767L8.982 1.566zM8 5c.535 0 .954.462.9.995l-.35 3.507a.552.552 0 0 1-1.1 0L7.1 5.995A.905.905 0 0 1 8 5zm.002 6a1 1 0 1 1 0 2 1 1 0 0 1 0-2z"/>
      </svg>
      {m.flow_prompt_invalid_structured_reference({
        tokens: invalidStructuredReferences.map((issue) => `{{${issue.token}}}`).join(", "),
      })}
    </div>
  {/if}
</div>
