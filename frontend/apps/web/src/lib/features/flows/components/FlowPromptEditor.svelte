<script lang="ts">
  import { tick, untrack, type Snippet } from "svelte";
  import type { FlowStep } from "@intric/intric-js";
  import { m } from "$lib/paraglide/messages";
  import { isFlowFormFieldNameUsableAsVariable } from "$lib/features/flows/flowFormSchema";
  import {
    getChipClasses,
    parsePromptSegments,
    collectUnresolvedTemplateTokens,
    collectInvalidStructuredOutputReferences,
    type VariableCategory,
    type VariableClassificationContext
  } from "$lib/features/flows/flowVariableTokens";
  import VariablePicker from "./VariablePicker.svelte";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as Card from "$lib/components/ui/card/index.js";

  let {
    value,
    disabled = false,
    placeholder = "",
    label = m.flow_step_prompt(),
    minHeight = 160,
    steps,
    currentStepOrder,
    formSchema,
    transcriptionEnabled,
    isAdvancedMode = false,
    toolbar,
    onChange,
    onCommit
  }: {
    value: string;
    disabled?: boolean;
    placeholder?: string;
    label?: string;
    minHeight?: number;
    steps: FlowStep[];
    currentStepOrder: number;
    formSchema:
      | {
          fields: {
            name: string;
            type: string;
            required?: boolean;
            options?: string[];
            order?: number;
          }[];
        }
      | undefined;
    transcriptionEnabled: boolean;
    isAdvancedMode?: boolean;
    toolbar?: Snippet;
    onChange?: (value: string) => void;
    onCommit?: (value: string) => void;
  } = $props();

  let currentEditorValue = $state(untrack(() => value));
  let lastCommittedValue = $state(untrack(() => value));
  let lastSeenPropValue = $state(untrack(() => value));

  // Sync external value prop changes into the editor
  $effect(() => {
    if (value !== lastSeenPropValue) {
      const isLocalEcho = value === currentEditorValue;
      lastSeenPropValue = value;
      if (!isLocalEcho) {
        currentEditorValue = value;
        lastCommittedValue = value;
        tick().then(() => autoResize());
      }
    }
  });

  // Initial auto-resize + commit on teardown
  $effect(() => {
    tick().then(() => autoResize());
    return () => {
      commitIfDirty(currentEditorValue);
    };
  });

  let textareaEl: HTMLTextAreaElement | null = $state(null);
  let mirrorEl: HTMLDivElement | null = $state(null);
  let autocompleteOpen = $state(false);
  let autocompleteQuery = $state("");
  let selectedSuggestionIndex = $state(0);
  let activeTrigger: "braces" | "at" | null = $state(null);
  let autocompleteAnchorIndex = $state(-1);
  let markerEl: HTMLSpanElement | null = $state(null);

  function resetAutocomplete() {
    autocompleteOpen = false;
    autocompleteQuery = "";
    activeTrigger = null;
    autocompleteAnchorIndex = -1;
  }

  // Build classification context
  const classificationContext = $derived.by(() =>
    buildContext(steps, formSchema, transcriptionEnabled, currentStepOrder)
  );

  function buildContext(
    steps: FlowStep[],
    formSchema:
      | {
          fields: {
            name: string;
            type: string;
            required?: boolean;
            options?: string[];
            order?: number;
          }[];
        }
      | undefined,
    transcriptionEnabled: boolean,
    currentStepOrder: number
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
    return {
      knownFieldNames,
      knownStepNames,
      stepOutputTypes,
      transcriptionEnabled,
      currentStepOrder
    };
  }

  // Parse segments for mirror rendering
  const segments = $derived(parsePromptSegments(currentEditorValue, classificationContext));

  // Build mirror segments with an optional marker at the autocomplete anchor position.
  type MirrorSegment = {
    type: "text" | "variable" | "marker";
    value: string;
    category?: VariableCategory;
  };
  const mirrorSegments = $derived.by(() =>
    buildMirrorSegments(segments, autocompleteAnchorIndex, autocompleteOpen)
  );

  function toMirror(seg: (typeof segments)[number]): MirrorSegment {
    return seg.type === "variable"
      ? { type: "variable", value: seg.value, category: seg.category }
      : { type: "text", value: seg.value };
  }

  function buildMirrorSegments(
    segs: typeof segments,
    anchorIdx: number,
    isOpen: boolean
  ): MirrorSegment[] {
    if (!isOpen || anchorIdx < 0) return segs.map(toMirror);
    const result: MirrorSegment[] = [];
    let charPos = 0;
    let markerInserted = false;
    for (const seg of segs) {
      const segLen = seg.value.length;
      if (!markerInserted && charPos + segLen > anchorIdx) {
        const offset = anchorIdx - charPos;
        if (seg.type === "text") {
          if (offset > 0) result.push({ type: "text", value: seg.value.slice(0, offset) });
          result.push({ type: "marker", value: "" });
          if (offset < segLen) result.push({ type: "text", value: seg.value.slice(offset) });
        } else {
          result.push({ type: "marker", value: "" });
          result.push(toMirror(seg));
        }
        markerInserted = true;
      } else if (!markerInserted && charPos + segLen === anchorIdx) {
        result.push(toMirror(seg));
        result.push({ type: "marker", value: "" });
        markerInserted = true;
      } else {
        result.push(toMirror(seg));
      }
      charPos += segLen;
    }
    if (!markerInserted) result.push({ type: "marker", value: "" });
    return result;
  }

  // Available variables for chip bar and autocomplete
  const availableVariables = $derived.by(() =>
    buildAvailableVariables(classificationContext, steps, isAdvancedMode)
  );

  type VariableSuggestion = {
    token: string;
    label: string;
    description: string;
    category: VariableCategory;
  };

  function buildAvailableVariables(
    ctx: VariableClassificationContext,
    steps: FlowStep[],
    showTechnical: boolean
  ): VariableSuggestion[] {
    const suggestions: VariableSuggestion[] = [];

    // Form fields
    for (const name of ctx.knownFieldNames) {
      suggestions.push({
        token: name,
        label: name,
        description: m.flow_variable_form_field(),
        category: "field"
      });
    }

    // System
    if (ctx.transcriptionEnabled) {
      suggestions.push({
        token: "transkribering",
        label: "transkribering",
        description: m.flow_variable_transcription(),
        category: "system"
      });
    }
    if (showTechnical && ctx.currentStepOrder > 1) {
      suggestions.push({
        token: "föregående_steg",
        label: "föregående_steg",
        description: m.flow_variable_previous_step(),
        category: "system"
      });
    }

    // Previous step name aliases
    for (const [order, name] of ctx.knownStepNames) {
      if (order < ctx.currentStepOrder && name) {
        suggestions.push({
          token: name,
          label: name,
          description: m.flow_variable_step_alias({ order: String(order) }),
          category: "step"
        });
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
          category: "step"
        });
      }
    }

    return suggestions;
  }

  // Chip bar variables (filtered in user mode)
  const chipBarVariables = $derived(
    isAdvancedMode
      ? availableVariables
      : availableVariables.filter((v) => v.category === "field" || v.category === "step")
  );

  // Unresolved count
  const unresolvedCount = $derived(
    collectUnresolvedTemplateTokens(
      currentEditorValue,
      new Set(availableVariables.map((v) => v.token))
    ).length
  );
  const invalidStructuredReferences = $derived(
    collectInvalidStructuredOutputReferences(currentEditorValue, steps, currentStepOrder)
  );

  // Filtered suggestions for autocomplete
  const filteredSuggestions = $derived(
    autocompleteQuery
      ? availableVariables.filter((v) =>
          v.label.toLowerCase().includes(autocompleteQuery.trim().toLowerCase())
        )
      : availableVariables
  );

  // Scroll sync
  function syncScroll() {
    if (mirrorEl && textareaEl) {
      mirrorEl.scrollTop = textareaEl.scrollTop;
    }
  }

  // Auto-resize textarea to fit content
  function autoResize() {
    if (!textareaEl) return;
    textareaEl.style.height = "auto";
    textareaEl.style.height = textareaEl.scrollHeight + "px";
  }

  let lastInputType = "";

  function handleInput(e: Event) {
    const target = e.target as HTMLTextAreaElement;
    lastInputType = (e as InputEvent).inputType ?? "";
    currentEditorValue = target.value;
    onChange?.(target.value);
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

  function findAtTriggerStart(text: string, cursor: number): number | null {
    if (findOpenTokenStart(text, cursor) !== null) return null;
    const beforeCursor = text.slice(0, cursor);
    const atIndex = beforeCursor.lastIndexOf("@");
    if (atIndex < 0) return null;
    if (atIndex > 0 && !/[\s([{]/.test(beforeCursor[atIndex - 1])) return null;
    if (beforeCursor.slice(atIndex + 1).includes(" ")) return null;
    return atIndex;
  }

  function updateAutocompleteState() {
    if (!textareaEl) {
      resetAutocomplete();
      return;
    }
    if (lastInputType.startsWith("delete")) {
      resetAutocomplete();
      return;
    }

    const cursor = textareaEl.selectionStart ?? currentEditorValue.length;

    const openIndex = findOpenTokenStart(currentEditorValue, cursor);
    if (openIndex !== null) {
      activeTrigger = "braces";
      autocompleteAnchorIndex = openIndex;
      autocompleteOpen = true;
      autocompleteQuery = currentEditorValue.slice(openIndex + 2, cursor).trimStart();
      selectedSuggestionIndex = 0;
      tick().then(measureAutocompletePosition);
      return;
    }

    if (lastInputType === "insertText" || activeTrigger === "at") {
      const atIndex = findAtTriggerStart(currentEditorValue, cursor);
      if (atIndex !== null) {
        activeTrigger = "at";
        autocompleteAnchorIndex = atIndex;
        autocompleteOpen = true;
        autocompleteQuery = currentEditorValue.slice(atIndex + 1, cursor);
        selectedSuggestionIndex = 0;
        tick().then(measureAutocompletePosition);
        return;
      }
    }

    resetAutocomplete();
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
      selectedSuggestionIndex =
        (selectedSuggestionIndex - 1 + filteredSuggestions.length) % filteredSuggestions.length;
    } else if (e.key === "Enter" || e.key === "Tab") {
      if (autocompleteOpen && filteredSuggestions.length > 0) {
        e.preventDefault();
        void applySuggestion(filteredSuggestions[selectedSuggestionIndex]);
      }
    } else if (e.key === "Escape") {
      resetAutocomplete();
    }
  }

  async function applySuggestion(suggestion: VariableSuggestion) {
    const token = `{{${suggestion.token}}}`;
    if (!textareaEl) return;

    const cursor = textareaEl.selectionStart ?? currentEditorValue.length;
    let replaceFrom: number | null = null;

    if (activeTrigger === "braces") {
      replaceFrom = findOpenTokenStart(currentEditorValue, cursor);
    } else if (activeTrigger === "at") {
      replaceFrom = findAtTriggerStart(currentEditorValue, cursor);
    }

    if (replaceFrom !== null) {
      const nextText =
        currentEditorValue.slice(0, replaceFrom) + token + currentEditorValue.slice(cursor);
      currentEditorValue = nextText;
      commitNow(nextText);
      await tick();
      if (textareaEl) {
        const nextCursor = replaceFrom + token.length;
        textareaEl.focus();
        textareaEl.setSelectionRange(nextCursor, nextCursor);
      }
    } else {
      void insertAtCursor(suggestion.token);
    }

    resetAutocomplete();
    autoResize();
  }

  async function insertAtCursor(variableToken: string) {
    const token = `{{${variableToken}}}`;
    if (!textareaEl) {
      const nextText = `${currentEditorValue}${token}`;
      currentEditorValue = nextText;
      commitNow(nextText);
      return;
    }
    const start = textareaEl.selectionStart ?? currentEditorValue.length;
    const end = textareaEl.selectionEnd ?? currentEditorValue.length;
    const nextText = currentEditorValue.slice(0, start) + token + currentEditorValue.slice(end);
    currentEditorValue = nextText;
    commitNow(nextText);
    await tick();
    if (textareaEl) {
      const nextCursor = start + token.length;
      textareaEl.focus();
      textareaEl.setSelectionRange(nextCursor, nextCursor);
    }
  }

  // Autocomplete position — read from marker span in mirror div
  let autocompletePosition = $state({ top: 0, left: 16 });

  function measureAutocompletePosition() {
    if (!mirrorEl || !textareaEl || !autocompleteOpen || !markerEl) {
      autocompletePosition = { top: 0, left: 16 };
      return;
    }
    const mirrorRect = mirrorEl.getBoundingClientRect();
    const markerRect = markerEl.getBoundingClientRect();
    const scrollTop = textareaEl.scrollTop;

    const rawTop = markerRect.bottom - mirrorRect.top - scrollTop;
    const top = Math.min(rawTop, textareaEl.clientHeight);

    const rawLeft = markerRect.left - mirrorRect.left;
    const maxLeft = textareaEl.clientWidth - 288;
    const left = Math.max(8, Math.min(rawLeft, maxLeft > 8 ? maxLeft : 8));

    autocompletePosition = { top, left };
  }

  function commitIfDirty(val: string) {
    if (val === lastCommittedValue) return;
    commitNow(val);
  }

  function commitNow(val: string) {
    lastCommittedValue = val;
    onCommit?.(val);
  }
</script>

<Card.Root
  class="flow-prompt-editor focus-within:ring-accent-default/30 transition-shadow focus-within:ring-2"
>
  <!-- Toolbar -->
  <div
    class="border-default bg-secondary/30 flex items-center justify-between border-b px-3 py-1.5"
  >
    <span class="text-muted text-[11px]">{label}</span>
    <div class="flex items-center gap-1">
      {#if toolbar}
        {@render toolbar()}
      {/if}
      {#if !disabled}
        <VariablePicker
          {steps}
          {currentStepOrder}
          {formSchema}
          {isAdvancedMode}
          {transcriptionEnabled}
          onInsert={(variable) => {
            const match = variable.match(/^\{\{(.+)\}\}$/);
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
      class="pointer-events-none absolute inset-0 overflow-hidden px-4 py-3 font-mono text-sm leading-relaxed break-words whitespace-pre-wrap"
      bind:this={mirrorEl}
    >
      {#each mirrorSegments as seg, index (`${seg.type}:${seg.value}:${index}`)}
        {#if seg.type === "marker"}<span
            bind:this={markerEl}
            aria-hidden="true"
            class="inline"
            style="width:0;overflow:hidden">&#8203;</span
          >{:else if seg.type === "text"}<span class="text-primary">{seg.value}</span>{:else}<span
            class="{getChipClasses(seg.category ?? 'unknown')} inline !px-0 !py-0 !text-sm"
            >{seg.value}</span
          >{/if}
      {/each}
      <span>&nbsp;</span>
    </div>

    <!-- Textarea layer (on top, transparent text, visible caret) -->
    <textarea
      bind:this={textareaEl}
      class="selection:bg-accent-dimmer selection:text-primary relative z-10 w-full overflow-hidden bg-transparent px-4 py-3 font-mono text-sm leading-relaxed text-transparent caret-gray-900 focus:outline-none dark:caret-gray-100"
      style={`min-height: ${minHeight}px`}
      oninput={handleInput}
      onkeydown={handleKeydown}
      onscroll={syncScroll}
      onclick={() => {
        lastInputType = "";
        updateAutocompleteState();
      }}
      onkeyup={(e) => {
        if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) {
          lastInputType = "";
          updateAutocompleteState();
        }
      }}
      onblur={() => commitIfDirty(currentEditorValue)}
      value={currentEditorValue}
      {disabled}
      {placeholder}
    ></textarea>

    <!-- Autocomplete dropdown -->
    {#if autocompleteOpen && filteredSuggestions.length > 0 && !disabled}
      <div
        class="border-default bg-primary absolute z-20 mt-1 max-h-48 w-72 overflow-y-auto rounded-lg border shadow-lg"
        style="top: {autocompletePosition.top}px; left: {autocompletePosition.left}px"
      >
        {#each filteredSuggestions as suggestion, i (suggestion.token)}
          <button
            type="button"
            class="hover:bg-hover-dimmer flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm"
            class:bg-hover-dimmer={i === selectedSuggestionIndex}
            onclick={() => void applySuggestion(suggestion)}
          >
            <span class={getChipClasses(suggestion.category)}>{suggestion.label}</span>
            <span class="text-muted text-[10px]">{suggestion.description}</span>
          </button>
        {/each}
      </div>
    {/if}
  </div>

  <!-- Quick-insert chip bar -->
  {#if chipBarVariables.length > 0 && !disabled}
    <div class="border-default bg-secondary/20 flex flex-wrap gap-1.5 border-t px-3 py-2">
      {#each chipBarVariables as v (v.token)}
        <button
          type="button"
          class="{getChipClasses(
            v.category
          )} cursor-pointer transition-all hover:scale-105 hover:shadow-sm active:scale-95"
          onclick={() => void insertAtCursor(v.token)}
        >
          {`{{${v.label}}}`}
        </button>
      {/each}
    </div>
  {/if}

  <!-- Unresolved variables warning -->
  {#if unresolvedCount > 0}
    <Alert.Root
      role="status"
      class="border-warning-default/40 bg-warning-dimmer text-warning-stronger rounded-none border-x-0 border-b-0 px-3 py-1.5 text-xs"
    >
      <svg class="size-3.5 shrink-0" viewBox="0 0 16 16" fill="currentColor">
        <path
          d="M8.982 1.566a1.13 1.13 0 0 0-1.96 0L.165 13.233c-.457.778.091 1.767.98 1.767h13.713c.889 0 1.438-.99.98-1.767L8.982 1.566zM8 5c.535 0 .954.462.9.995l-.35 3.507a.552.552 0 0 1-1.1 0L7.1 5.995A.905.905 0 0 1 8 5zm.002 6a1 1 0 1 1 0 2 1 1 0 0 1 0-2z"
        />
      </svg>
      {unresolvedCount}
      {m.flow_prompt_unresolved_variables()}
    </Alert.Root>
  {/if}

  {#if invalidStructuredReferences.length > 0}
    <Alert.Root
      role="status"
      class="border-warning-default/40 bg-warning-dimmer text-warning-stronger rounded-none border-x-0 border-b-0 px-3 py-1.5 text-xs"
    >
      <svg class="size-3.5 shrink-0" viewBox="0 0 16 16" fill="currentColor">
        <path
          d="M8.982 1.566a1.13 1.13 0 0 0-1.96 0L.165 13.233c-.457.778.091 1.767.98 1.767h13.713c.889 0 1.438-.99.98-1.767L8.982 1.566zM8 5c.535 0 .954.462.9.995l-.35 3.507a.552.552 0 0 1-1.1 0L7.1 5.995A.905.905 0 0 1 8 5zm.002 6a1 1 0 1 1 0 2 1 1 0 0 1 0-2z"
        />
      </svg>
      {m.flow_prompt_invalid_structured_reference({
        tokens: invalidStructuredReferences.map((issue) => `{{${issue.token}}}`).join(", ")
      })}
    </Alert.Root>
  {/if}
</Card.Root>
