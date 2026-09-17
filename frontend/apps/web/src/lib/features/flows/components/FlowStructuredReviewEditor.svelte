<script lang="ts">
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import { m } from "$lib/paraglide/messages";
  import {
    parseReviewValue,
    reviewChangedPaths,
    reviewSchema,
    type ReviewSchema
  } from "../structuredReview";
  import FlowStructuredReviewField from "./FlowStructuredReviewField.svelte";

  let {
    text,
    schema,
    disabled,
    original = false,
    originalText,
    showOriginal = $bindable(false),
    onChange
  }: {
    text: string;
    schema: ReviewSchema | null | undefined;
    disabled: boolean;
    original?: boolean;
    originalText?: string;
    showOriginal?: boolean;
    onChange: (text: string) => void;
  } = $props();
  let advanced = $state(false);
  const originalValue = $derived(
    originalText === undefined ? undefined : parseReviewValue(originalText)
  );
  const currentValue = $derived(parseReviewValue(text));
  const changedPaths = $derived(
    originalValue !== undefined && currentValue !== undefined
      ? reviewChangedPaths(originalValue, currentValue)
      : new Set<string>()
  );
  const value = $derived(showOriginal ? originalValue : currentValue);
  const readable = $derived(value !== null && typeof value === "object");
  const id = $props.id();
</script>

<div class="flex max-w-[53.75rem] min-w-0 flex-col gap-4 2xl:max-w-[62.5rem]">
  <div class="flex min-w-0 flex-col gap-1">
    <div class="flex min-h-10 items-center justify-between gap-3">
      {#if !original}
        <h3 class="text-primary min-w-0 text-sm font-semibold">
          {showOriginal
            ? m.flow_run_review_original_payload()
            : m.flow_run_review_current_payload()}
        </h3>
      {/if}
      <div class="flex shrink-0 items-center gap-1">
        {#if originalValue !== undefined && !original}
          <Button
            type="button"
            variant={showOriginal ? "secondary" : "outline"}
            class="min-h-10"
            aria-pressed={showOriginal}
            onclick={() => {
              showOriginal = !showOriginal;
              advanced = false;
            }}
          >
            {showOriginal ? m.flow_run_review_back_to_edit() : m.flow_run_review_show_original()}
          </Button>
        {/if}
        <Button
          type="button"
          variant={advanced ? "secondary" : "outline"}
          class="min-h-10"
          disabled={!readable}
          aria-pressed={advanced}
          onclick={() => (advanced = !advanced)}
          >{advanced || !readable
            ? m.flow_run_review_show_fields()
            : m.flow_run_review_show_json()}</Button
        >
      </div>
    </div>
    {#if !original && (showOriginal || !disabled)}
      <p class="text-secondary max-w-prose text-sm leading-relaxed">
        {showOriginal ? m.flow_run_review_original_help() : m.flow_run_review_fields_help()}
      </p>
    {/if}
  </div>
  {#if advanced || !readable}
    <Field.Field>
      <Field.Label for={id}>{m.flow_run_review_json_payload()}</Field.Label>
      <Textarea
        {id}
        value={showOriginal ? originalText : text}
        disabled={disabled || showOriginal || original}
        aria-invalid={!readable}
        class="min-h-72 font-mono text-xs"
        spellcheck={false}
        oninput={(event) => onChange(event.currentTarget.value)}
      />
      {#if !readable}<Field.Description>{m.flow_run_review_payload_invalid()}</Field.Description
        >{/if}
    </Field.Field>
  {:else}
    <FlowStructuredReviewField
      schema={reviewSchema(schema)}
      {value}
      {disabled}
      readOnly={original || showOriginal}
      originalValue={showOriginal ? undefined : originalValue}
      changedPaths={showOriginal ? undefined : changedPaths}
      label={m.flow_run_review_current_payload()}
      onChange={(next) => onChange(JSON.stringify(next, null, 2))}
    />
  {/if}
</div>
