<script lang="ts">
  import { tick, untrack } from "svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import { m } from "$lib/paraglide/messages";
  import {
    emptyReviewValue,
    isReviewObject,
    replaceReviewProperty,
    reviewFieldKind,
    reviewFieldLabel,
    reviewItemPreview,
    reviewObjectFields,
    reviewSchema,
    type ReviewSchema,
    type ReviewValue
  } from "../structuredReview";
  import FlowStructuredReviewField from "./FlowStructuredReviewField.svelte";

  let {
    schema,
    value,
    label,
    preview = "",
    depth = 0,
    disabled = false,
    onChange
  }: {
    schema: ReviewSchema;
    value: ReviewValue | undefined;
    label: string;
    preview?: string;
    depth?: number;
    disabled?: boolean;
    onChange: (value: ReviewValue) => void;
  } = $props();
  const id = $props.id();
  const kind = $derived(depth > 20 ? "unsupported" : reviewFieldKind(schema, value));
  const description = $derived(typeof schema.description === "string" ? schema.description : "");
  const items = $derived(Array.isArray(value) ? value : []);
  const choices = $derived(
    Array.isArray(schema.enum)
      ? schema.enum.filter((choice): choice is string => typeof choice === "string")
      : []
  );
  let open = $state(untrack(() => depth < 2));
  let addButton = $state<HTMLButtonElement | null>(null);

  async function removeItem(index: number) {
    onChange(items.filter((_, position) => position !== index));
    await tick();
    addButton?.focus();
  }
</script>

{#snippet contents()}
  {#if kind === "object"}
    <Field.Group class="gap-5">
      {#each reviewObjectFields(schema, value) as field (field.key)}
        <FlowStructuredReviewField
          schema={field.schema}
          value={isReviewObject(value) ? value[field.key] : undefined}
          label={reviewFieldLabel(field.schema, field.key)}
          depth={depth + 1}
          {disabled}
          onChange={(next) => onChange(replaceReviewProperty(value, field.key, next))}
        />
      {/each}
    </Field.Group>
  {:else if kind === "array"}
    <div class="flex min-w-0 flex-col gap-4">
      {#if !items.length}<p class="text-muted text-sm">{m.flow_run_review_no_items()}</p>{/if}
      {#each items as item, index (index)}
        <div class="border-default flex min-w-0 flex-col gap-2 border-b pb-4 last:border-b-0">
          <FlowStructuredReviewField
            schema={reviewSchema(schema.items)}
            value={item}
            label={m.flow_run_review_item({ number: index + 1 })}
            preview={reviewItemPreview(reviewSchema(schema.items), item)}
            depth={depth + 1}
            {disabled}
            onChange={(next) =>
              onChange(items.map((existing, position) => (position === index ? next : existing)))}
          />
          <Button
            type="button"
            variant="ghost"
            class="min-h-10 self-start"
            disabled={disabled ||
              (typeof schema.minItems === "number" && items.length <= schema.minItems)}
            aria-label={m.flow_run_review_remove_item({ number: index + 1 })}
            onclick={() => void removeItem(index)}>{m.remove()}</Button
          >
        </div>
      {/each}
      {#if reviewFieldKind(reviewSchema(schema.items)) !== "unsupported"}
        <Button
          bind:ref={addButton}
          type="button"
          variant="outline"
          class="min-h-10 self-start"
          disabled={disabled ||
            (typeof schema.maxItems === "number" && items.length >= schema.maxItems)}
          onclick={() => onChange([...items, emptyReviewValue(reviewSchema(schema.items))])}
          >{m.flow_run_review_add_item()}</Button
        >
      {/if}
    </div>
  {/if}
{/snippet}

{#if kind === "object" || kind === "array"}
  {#if depth === 0}
    {@render contents()}
  {:else}
    <details bind:open class="border-default min-w-0 border-t">
      <summary
        class="text-primary focus-visible:ring-accent-default cursor-pointer py-3 text-sm font-medium [overflow-wrap:anywhere] focus-visible:ring-2"
      >
        {label}
        {#if preview}<span class="text-muted font-normal">: {preview}</span>{/if}
        {#if kind === "array"}<span class="text-muted ml-2 font-normal tabular-nums"
            >({items.length})</span
          >{/if}
      </summary>
      {#if open}
        <div class="flex min-w-0 flex-col gap-4 pb-4 pl-3 sm:pl-5">
          {#if description}<p class="text-muted text-sm leading-relaxed">{description}</p>{/if}
          {@render contents()}
        </div>
      {/if}
    </details>
  {/if}
{:else}
  <Field.Field>
    {#if kind === "readonly" || kind === "unsupported"}
      <p class="text-primary text-sm font-medium">{label}</p>
    {:else}
      <Field.Label for={id}>{label}</Field.Label>
    {/if}
    {#if kind === "string"}
      <Textarea
        {id}
        value={typeof value === "string" ? value : ""}
        {disabled}
        aria-describedby={description ? id + "-help" : undefined}
        class="min-h-12 leading-relaxed"
        rows={2}
        oninput={(event) => onChange(event.currentTarget.value)}
      />
    {:else if kind === "enum" || kind === "boolean"}
      <select
        {id}
        {disabled}
        class="border-input bg-primary focus-visible:ring-accent-default min-h-10 w-full rounded-lg border px-3 text-base focus-visible:ring-2 disabled:opacity-50 md:text-sm"
        aria-describedby={description ? id + "-help" : undefined}
        value={kind === "boolean"
          ? typeof value === "boolean"
            ? String(value)
            : ""
          : typeof value === "string"
            ? JSON.stringify(value)
            : ""}
        onchange={(event) =>
          onChange(
            kind === "boolean"
              ? event.currentTarget.value === "true"
              : (choices.find((choice) => JSON.stringify(choice) === event.currentTarget.value) ??
                  "")
          )}
      >
        <option value="" disabled>{m.flow_run_review_choose_value()}</option>
        {#if kind === "boolean"}
          <option value="true">{m.yes()}</option><option value="false">{m.no()}</option>
        {:else}
          {#if typeof value === "string" && !choices.includes(value)}
            <option value={JSON.stringify(value)} disabled
              >{value || m.flow_run_review_choose_value()}</option
            >
          {/if}
          {#each choices as choice (choice)}<option value={JSON.stringify(choice)}
              >{reviewFieldLabel({}, choice) || m.flow_run_review_empty_value()}</option
            >{/each}
        {/if}
      </select>
    {:else if kind === "number"}
      <Input
        {id}
        type="number"
        value={typeof value === "number" ? value : undefined}
        {disabled}
        step={schema.type === "integer" ? 1 : "any"}
        aria-describedby={description ? id + "-help" : undefined}
        class="min-h-10"
        oninput={(event) =>
          onChange(
            Number.isFinite(event.currentTarget.valueAsNumber)
              ? event.currentTarget.valueAsNumber
              : ""
          )}
      />
    {:else}
      <p
        {id}
        class="text-primary text-sm leading-relaxed [overflow-wrap:anywhere] whitespace-pre-wrap"
      >
        {value === undefined
          ? m.flow_run_review_empty_value()
          : typeof value === "string"
            ? value
            : JSON.stringify(value, null, 2)}
      </p>
      {#if kind === "unsupported"}<p class="text-muted text-sm">
          {m.flow_run_review_unsupported_field()}
        </p>{/if}
    {/if}
    {#if description}<Field.Description id={id + "-help"}>{description}</Field.Description>{/if}
  </Field.Field>
{/if}
