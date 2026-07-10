<script lang="ts">
  import { tick, untrack, type Snippet } from "svelte";
  import type { FlowStep } from "@eneo/eneo-js";
  import { m } from "$lib/paraglide/messages";
  import {
    getChipClasses,
    parsePromptSegments,
    collectTemplateValidationIssues,
    type TemplateValidationIssue
  } from "$lib/features/flows/flowVariableTokens";
  import VariablePicker from "./VariablePicker.svelte";
  import { findOpenTokenStart, findAtTriggerStart } from "./flowPromptAutocomplete";
  import { buildMirrorSegments } from "./flowPromptMirror";
  import {
    buildContext,
    buildAvailableVariables,
    type VariableSuggestion
  } from "./flowPromptVariables";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import { CircleAlert } from "lucide-svelte";

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
    invalid = false,
    ariaDescribedby,
    focusOnMount = false,
    toolbar,
    onChange,
    onCommit,
    onFocused
  }: {
    value: string;
    disabled?: boolean;
    placeholder?: string;
    label?: string;
    invalid?: boolean;
    ariaDescribedby?: string;
    focusOnMount?: boolean;
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
    onFocused?: () => void;
  } = $props();

  const MAX_VISIBLE_TEMPLATE_VALIDATION_ISSUES = 5;

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

  // Focus the textarea when the parent requests it (e.g. the step capsule's
  // "add instruction" action, which opens this section and moves focus here).
  // `focusOnMount` is a consume-once flag, not a counter: the section unmounts
  // while collapsed, so on open this editor mounts fresh, reads the flag once,
  // focuses, then calls `onFocused` so the parent clears it. Reading
  // `textareaEl` keeps it correct when the flag is already set before mount.
  $effect(() => {
    if (!focusOnMount) return;
    const el = textareaEl;
    if (!el) return;
    el.focus();
    onFocused?.();
  });

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

  // Parse segments for mirror rendering
  const segments = $derived(parsePromptSegments(currentEditorValue, classificationContext));

  // Build mirror segments with an optional marker at the autocomplete anchor position.
  const mirrorSegments = $derived.by(() =>
    buildMirrorSegments(segments, autocompleteAnchorIndex, autocompleteOpen)
  );

  // Available variables for chip bar and autocomplete
  const availableVariables = $derived.by(() =>
    buildAvailableVariables(classificationContext, steps, isAdvancedMode)
  );

  // Chip bar variables (filtered in user mode)
  const chipBarVariables = $derived(
    isAdvancedMode
      ? availableVariables
      : availableVariables.filter((v) => v.category === "field" || v.category === "step")
  );

  const templateValidationIssues = $derived(
    collectTemplateValidationIssues(currentEditorValue, classificationContext)
  );
  const visibleTemplateValidationIssues = $derived(
    templateValidationIssues.slice(0, MAX_VISIBLE_TEMPLATE_VALIDATION_ISSUES)
  );
  const hiddenTemplateValidationIssueCount = $derived(
    Math.max(0, templateValidationIssues.length - visibleTemplateValidationIssues.length)
  );

  const templateValidationIssueMessages: Record<TemplateValidationIssue["reason"], () => string> = {
    deleted_step: m.flow_template_issue_deleted_step,
    unavailable_step: m.flow_template_issue_unavailable_step,
    non_json_output: m.flow_template_issue_non_json_output,
    unknown_variable: m.flow_template_issue_unknown_variable
  };

  function getTemplateValidationIssueText(issue: TemplateValidationIssue): string {
    return templateValidationIssueMessages[issue.reason]();
  }

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
    setEditorValue(target.value);
    updateAutocompleteState();
    autoResize();
  }

  function setEditorValue(nextValue: string) {
    currentEditorValue = nextValue;
    onChange?.(nextValue);
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
      setEditorValue(nextText);
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
      setEditorValue(nextText);
      commitNow(nextText);
      return;
    }
    const start = textareaEl.selectionStart ?? currentEditorValue.length;
    const end = textareaEl.selectionEnd ?? currentEditorValue.length;
    const nextText = currentEditorValue.slice(0, start) + token + currentEditorValue.slice(end);
    setEditorValue(nextText);
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
  class="flow-prompt-editor focus-within:ring-accent-default/30 transition-shadow focus-within:ring-2 {invalid
    ? 'ring-warning-default/40 ring-1'
    : ''}"
>
  <!-- Toolbar -->
  <div
    class="border-default bg-secondary/30 flex items-center justify-between border-b px-3 py-1.5"
  >
    <span class="text-muted text-xs">{label}</span>
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
      class="pointer-events-none absolute inset-0 overflow-hidden px-4 py-3 font-mono text-base leading-relaxed break-words whitespace-pre-wrap sm:text-sm"
      bind:this={mirrorEl}
    >
      {#each mirrorSegments as seg, index (`${seg.type}:${seg.value}:${index}`)}
        {#if seg.type === "marker"}<span
            bind:this={markerEl}
            aria-hidden="true"
            class="inline"
            style="width:0;overflow:hidden">&#8203;</span
          >{:else if seg.type === "text"}<span class="text-primary">{seg.value}</span>{:else}<span
            class="{getChipClasses(
              seg.category ?? 'unknown'
            )} inline !px-0 !py-0 !text-base sm:!text-sm">{seg.value}</span
          >{/if}
      {/each}
      <span>&nbsp;</span>
    </div>

    <!-- Textarea layer (on top, transparent text, visible caret) -->
    <textarea
      bind:this={textareaEl}
      class="selection:bg-accent-dimmer selection:text-primary relative z-10 w-full overflow-hidden bg-transparent px-4 py-3 font-mono text-base leading-relaxed text-transparent caret-foreground focus:outline-none sm:text-sm"
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
      aria-label={label}
      aria-invalid={invalid || undefined}
      aria-describedby={ariaDescribedby}></textarea>

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
            {#if suggestion.displayToken}
              <span class="text-muted font-mono text-xs">{`{{${suggestion.token}}}`}</span>
            {/if}
            <span class="text-muted text-xs">{suggestion.description}</span>
          </button>
        {/each}
      </div>
    {/if}
  </div>

  <!-- Quick-insert chip bar — kept out of Enkel so the editor stays calm; the
       toolbar's variable picker ({}) still inserts variables there. -->
  {#if chipBarVariables.length > 0 && !disabled && isAdvancedMode}
    <div class="border-default bg-secondary/20 flex flex-wrap gap-1.5 border-t px-3 py-2">
      {#each chipBarVariables as v (v.token)}
        <button
          type="button"
          class="{getChipClasses(
            v.category
          )} cursor-pointer transition-all hover:scale-105 hover:shadow-sm active:scale-95"
          onclick={() => void insertAtCursor(v.token)}
        >
          {`{{${v.displayToken ? v.token : v.label}}}`}
        </button>
      {/each}
    </div>
  {/if}

  {#if templateValidationIssues.length > 0}
    <Alert.Root
      role="status"
      class="border-warning-default/40 bg-warning-dimmer text-warning-stronger rounded-none border-x-0 border-b-0 px-3 py-2 text-xs"
    >
      <CircleAlert class="shrink-0" />
      <Alert.Title>{m.flow_template_issues_title()}</Alert.Title>
      <Alert.Description class="text-warning-stronger flex flex-col gap-1.5">
        <p>{m.flow_template_issues_description()}</p>
        <ul class="flex flex-col gap-1">
          {#each visibleTemplateValidationIssues as issue (issue.token)}
            <li class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
              <code
                class="bg-primary/70 text-warning-stronger max-w-full rounded-md px-1.5 py-0.5 font-mono text-xs break-all"
                >{`{{${issue.token}}}`}</code
              >
              <span>{getTemplateValidationIssueText(issue)}</span>
            </li>
          {/each}
        </ul>
        {#if hiddenTemplateValidationIssueCount > 0}
          <p>
            {m.flow_template_issues_more({
              count: String(hiddenTemplateValidationIssueCount)
            })}
          </p>
        {/if}
      </Alert.Description>
    </Alert.Root>
  {/if}
</Card.Root>
