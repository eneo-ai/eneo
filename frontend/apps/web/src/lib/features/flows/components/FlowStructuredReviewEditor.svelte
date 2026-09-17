<script lang="ts">
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import { m } from "$lib/paraglide/messages";
  import { parseReviewValue, reviewSchema, type ReviewSchema } from "../structuredReview";
  import FlowStructuredReviewField from "./FlowStructuredReviewField.svelte";

  let {
    text,
    schema,
    disabled,
    original = false,
    onChange
  }: {
    text: string;
    schema: ReviewSchema | null | undefined;
    disabled: boolean;
    original?: boolean;
    onChange: (text: string) => void;
  } = $props();
  let advanced = $state(false);
  const value = $derived(parseReviewValue(text));
  const readable = $derived(value !== null && typeof value === "object");
  const id = $props.id();
</script>

<div class="flex min-w-0 flex-col gap-4">
  <div class="flex flex-wrap items-start justify-between gap-3">
    <div class="flex flex-col gap-1">
      {#if !original}
        <h3 class="text-primary text-sm font-medium">{m.flow_run_review_current_payload()}</h3>
        {#if !disabled}<p class="text-muted text-sm leading-relaxed">
            {m.flow_run_review_fields_help()}
          </p>{/if}
      {/if}
    </div>
    <Button
      type="button"
      variant="ghost"
      class="min-h-10"
      disabled={!readable}
      aria-pressed={advanced || !readable}
      onclick={() => (advanced = !advanced)}
      >{advanced || !readable
        ? m.flow_run_review_show_fields()
        : m.flow_run_review_show_json()}</Button
    >
  </div>
  {#if advanced || !readable}
    <Field.Field>
      <Field.Label for={id}>{m.flow_run_review_json_payload()}</Field.Label>
      <Textarea
        {id}
        value={text}
        {disabled}
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
      label={m.flow_run_review_current_payload()}
      onChange={(next) => onChange(JSON.stringify(next, null, 2))}
    />
  {/if}
</div>
