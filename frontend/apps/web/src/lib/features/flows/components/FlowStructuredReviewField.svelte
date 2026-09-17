<script lang="ts">
  import { tick, untrack } from "svelte";
  import ChevronRight from "lucide-svelte/icons/chevron-right";
  import Info from "lucide-svelte/icons/info";
  import { IconTrash } from "@eneo/icons/trash";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import { m } from "$lib/paraglide/messages";
  import {
    emptyReviewValue,
    isReviewObject,
    replaceReviewProperty,
    reviewCollectionCounts,
    reviewFieldKind,
    reviewFieldLabel,
    reviewItemPreview,
    reviewObjectFields,
    reviewPropertyPath,
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
    readOnly = false,
    inline = false,
    initiallyOpen,
    originalValue,
    changedPaths = new Set<string>(),
    path = "",
    onChange
  }: {
    schema: ReviewSchema;
    value: ReviewValue | undefined;
    label: string;
    preview?: string;
    depth?: number;
    disabled?: boolean;
    readOnly?: boolean;
    inline?: boolean;
    initiallyOpen?: boolean;
    originalValue?: ReviewValue;
    changedPaths?: ReadonlySet<string>;
    path?: string;
    onChange: (value: ReviewValue) => void;
  } = $props();
  const id = $props.id();
  const kind = $derived(depth > 20 ? "unsupported" : reviewFieldKind(schema, value));
  const description = $derived(typeof schema.description === "string" ? schema.description : "");
  const items = $derived(Array.isArray(value) ? value : []);
  const fields = $derived(reviewObjectFields(schema, value, originalValue));
  const collections = $derived(reviewCollectionCounts(schema, value));
  // A fixed heading plus one list is already fully described by the section summary.
  const singleCollection = $derived(
    depth > 0 &&
      fields.some((field) => field.schema.const === label) &&
      fields.filter((field) => field.schema.type === "array").length === 1 &&
      fields.every(
        (field) =>
          field.schema.type === "array" ||
          (field.schema.const === label &&
            isReviewObject(value) &&
            value[field.key] === label &&
            (!isReviewObject(originalValue) || originalValue[field.key] === label))
      )
      ? fields.find((field) => field.schema.type === "array")?.key
      : undefined
  );
  const changed = $derived(changedPaths.has(path));
  const choices = $derived(
    Array.isArray(schema.enum)
      ? schema.enum.filter((choice): choice is string => typeof choice === "string")
      : []
  );
  let open = $state(
    untrack(() => (initiallyOpen ?? depth < 2) && !(Array.isArray(value) && value.length === 0))
  );
  let helpOpen = $state(false);
  let previousOpen = $state(false);
  let addButton = $state<HTMLButtonElement | null>(null);

  let itemList = $state<HTMLDivElement | null>(null);
  let addedIndex = $state<number | null>(null);

  async function addItem() {
    addedIndex = items.length;
    onChange([...items, emptyReviewValue(reviewSchema(schema.items))]);
    await tick();
    const rows = itemList?.querySelectorAll(":scope > [data-review-item]");
    rows?.[rows.length - 1]
      ?.querySelector<HTMLElement>("textarea, input, select, summary")
      ?.focus();
  }

  async function removeItem(index: number) {
    onChange(items.filter((_, position) => position !== index));
    await tick();
    addButton?.focus();
  }
</script>

{#snippet changedLabel()}
  {#if changed}
    <span
      class="bg-warning-dimmer text-warning-stronger shrink-0 rounded px-1.5 py-0.5 text-xs font-medium"
    >
      {m.flow_run_review_changed()}
    </span>
  {/if}
{/snippet}

{#snippet previousValue()}
  {#if changed && kind !== "object"}
    <details bind:open={previousOpen} class="border-default min-w-0 rounded-md border px-3">
      <summary
        class="text-secondary focus-visible:ring-accent-default cursor-pointer py-2 text-sm focus-visible:ring-2"
      >
        {m.flow_run_review_previous_value()}
      </summary>
      {#if previousOpen}<div class="pb-3">
          <FlowStructuredReviewField
            {schema}
            value={originalValue}
            label={m.flow_run_review_previous_value()}
            depth={0}
            readOnly
            disabled
            onChange={() => {}}
          />
        </div>{/if}
    </details>
  {/if}
{/snippet}

{#snippet contents()}
  {#if kind === "object"}
    <div class="flex min-w-0 flex-col gap-3">
      {#each fields as field (field.key)}
        {#if !singleCollection || field.key === singleCollection}
          <FlowStructuredReviewField
            schema={field.schema}
            value={isReviewObject(value) ? value[field.key] : undefined}
            originalValue={isReviewObject(originalValue) ? originalValue[field.key] : undefined}
            {changedPaths}
            path={reviewPropertyPath(path, field.key)}
            label={reviewFieldLabel(field.schema, field.key)}
            depth={depth + 1}
            {disabled}
            {readOnly}
            inline={field.key === singleCollection}
            onChange={(next) => onChange(replaceReviewProperty(value, field.key, next))}
          />
        {/if}
      {/each}
    </div>
  {:else if kind === "array"}
    <div bind:this={itemList} class="flex min-w-0 flex-col gap-2">
      {#if !items.length}<p class="text-secondary py-1 text-sm">
          {m.flow_run_review_no_items()}
        </p>{/if}
      {#each items as item, index (index)}
        <div
          data-review-item
          class="border-default flex min-w-0 items-start gap-2 border-b py-1 last:border-b-0"
        >
          <div class="min-w-0 flex-1">
            <FlowStructuredReviewField
              schema={reviewSchema(schema.items)}
              value={item}
              label={m.flow_run_review_item({ number: index + 1 })}
              preview={reviewItemPreview(reviewSchema(schema.items), item)}
              depth={depth + 1}
              initiallyOpen={index === addedIndex ? true : undefined}
              {disabled}
              {readOnly}
              onChange={(next) =>
                onChange(items.map((existing, position) => (position === index ? next : existing)))}
            />
          </div>
          {#if !readOnly}
            <Button
              type="button"
              variant="ghost"
              size="icon"
              class="mt-0.5 size-10 shrink-0"
              disabled={disabled ||
                (typeof schema.minItems === "number" && items.length <= schema.minItems)}
              aria-label={m.flow_run_review_remove_item({ number: index + 1 })}
              title={m.flow_run_review_remove_item({ number: index + 1 })}
              onclick={() => void removeItem(index)}><IconTrash class="size-4" /></Button
            >
          {/if}
        </div>
      {/each}
      {#if !readOnly && reviewFieldKind(reviewSchema(schema.items)) !== "unsupported"}
        <Button
          bind:ref={addButton}
          type="button"
          variant="outline"
          class="mt-1 min-h-10 self-start"
          disabled={disabled ||
            (typeof schema.maxItems === "number" && items.length >= schema.maxItems)}
          onclick={() => void addItem()}>{m.flow_run_review_add_item()}</Button
        >
      {/if}
      {@render previousValue()}
    </div>
  {/if}
{/snippet}

{#if kind === "object" || kind === "array"}
  {#if depth === 0 || inline}
    {@render contents()}
  {:else}
    <details bind:open class="border-default min-w-0 border-t">
      <summary
        class="text-primary hover:bg-hover-dimmer focus-visible:ring-accent-default flex min-h-11 cursor-pointer list-none items-start gap-2 rounded-sm py-2.5 text-sm focus-visible:ring-2 [&::-webkit-details-marker]:hidden"
      >
        <ChevronRight class="mt-0.5 size-4 shrink-0 {open ? 'rotate-90' : ''}" aria-hidden="true" />
        <span class="min-w-0 flex-1 [overflow-wrap:anywhere]">
          <span class={preview ? "leading-relaxed" : "font-semibold"}>{preview || label}</span>
          {#if kind === "object" && !preview && collections.length}
            <span class="text-secondary mt-0.5 block text-xs leading-relaxed">
              {collections
                .map((collection) =>
                  m.flow_run_review_collection_count({
                    label: collection.label,
                    count: collection.count
                  })
                )
                .join(" · ")}
            </span>
          {/if}
        </span>
        {#if kind === "array"}<span class="text-secondary shrink-0 text-sm tabular-nums"
            >{items.length}</span
          >{/if}
        {@render changedLabel()}
      </summary>
      {#if open}
        <div class="flex min-w-0 flex-col gap-3 pb-3 pl-3 sm:pl-6">
          {#if description}<p class="text-secondary max-w-prose text-sm leading-relaxed">
              {description}
            </p>{/if}
          {@render contents()}
        </div>
      {/if}
    </details>
  {/if}
{:else}
  <Field.Field class="min-w-0 gap-1.5">
    <div class="flex min-h-8 items-center gap-2">
      {#if readOnly || kind === "readonly" || kind === "unsupported"}
        <p class="text-secondary text-sm font-medium">{label}</p>
      {:else}
        <Field.Label for={id}>{label}</Field.Label>
      {/if}
      {@render changedLabel()}
      {#if description && !readOnly}
        <Button
          type="button"
          variant="ghost"
          size="icon"
          class="ml-auto size-10 shrink-0"
          aria-label={m.flow_run_review_field_help({ label })}
          aria-expanded={helpOpen}
          aria-controls={helpOpen ? id + "-help" : undefined}
          onclick={() => (helpOpen = !helpOpen)}
        >
          <Info class="size-4" aria-hidden="true" />
        </Button>
      {/if}
    </div>
    {#if description && helpOpen}<Field.Description id={id + "-help"} class="max-w-prose pb-1"
        >{description}</Field.Description
      >{/if}
    {#if readOnly || kind === "readonly" || kind === "unsupported"}
      <p
        class="text-primary max-w-prose text-sm leading-relaxed [overflow-wrap:anywhere] whitespace-pre-wrap"
      >
        {value === undefined || value === ""
          ? m.flow_run_review_empty_value()
          : typeof value === "string"
            ? kind === "enum"
              ? reviewFieldLabel({}, value)
              : value
            : typeof value === "boolean"
              ? value
                ? m.yes()
                : m.no()
              : JSON.stringify(value, null, 2)}
      </p>
      {#if kind === "unsupported" && !readOnly}<p class="text-secondary text-sm">
          {m.flow_run_review_unsupported_field()}
        </p>{/if}
    {:else if kind === "string"}
      <Textarea
        {id}
        value={typeof value === "string" ? value : ""}
        {disabled}
        aria-describedby={helpOpen ? id + "-help" : undefined}
        class="min-h-10 leading-relaxed"
        rows={2}
        oninput={(event) => onChange(event.currentTarget.value)}
      />
    {:else if kind === "enum" || kind === "boolean"}
      <select
        {id}
        {disabled}
        class="border-input bg-primary focus-visible:ring-accent-default min-h-10 w-full rounded-lg border px-3 text-base focus-visible:ring-2 disabled:opacity-50 md:text-sm"
        aria-describedby={helpOpen ? id + "-help" : undefined}
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
        aria-describedby={helpOpen ? id + "-help" : undefined}
        class="min-h-10"
        oninput={(event) =>
          onChange(
            Number.isFinite(event.currentTarget.valueAsNumber)
              ? event.currentTarget.valueAsNumber
              : ""
          )}
      />
    {/if}
    {@render previousValue()}
  </Field.Field>
{/if}
