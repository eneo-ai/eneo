<script lang="ts">
  import { tick, untrack } from "svelte";
  import ChevronRight from "lucide-svelte/icons/chevron-right";
  import Info from "lucide-svelte/icons/info";
  import { IconTrash } from "@eneo/icons/trash";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
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
  // A fixed field that restates the heading above it is already read; showing
  // it again reads as a duplicate rather than as information.
  const titleFieldKey = $derived(
    // Never hide the only thing a section has; an empty section is a dead end.
    depth > 0 && fields.length > 1
      ? fields.find(
          (field) =>
            field.schema.const === label &&
            isReviewObject(value) &&
            value[field.key] === label &&
            (!isReviewObject(originalValue) || originalValue[field.key] === label)
        )?.key
      : undefined
  );
  const shownFields = $derived(
    fields.filter(
      (field) =>
        (!singleCollection || field.key === singleCollection) && field.key !== titleFieldKey
    )
  );
  const changed = $derived(changedPaths.has(path));
  const choices = $derived(
    Array.isArray(schema.enum)
      ? schema.enum.filter((choice): choice is string => typeof choice === "string")
      : []
  );
  // An enum may offer the empty string as a real choice, so "chosen" is decided
  // by the contract rather than by emptiness. Values are encoded because the
  // select primitive reads the empty string as "nothing chosen".
  const chosen = $derived(
    kind === "boolean"
      ? typeof value === "boolean"
      : typeof value === "string" && (value !== "" || choices.includes(""))
  );
  const choiceValue = $derived(
    !chosen ? "" : kind === "boolean" ? String(value) : JSON.stringify(value)
  );
  const choiceLabel = $derived(
    !chosen
      ? m.flow_run_review_choose_value()
      : kind === "boolean"
        ? value
          ? m.yes()
          : m.no()
        : typeof value === "string"
          ? reviewFieldLabel({}, value) || m.flow_run_review_empty_value()
          : m.flow_run_review_choose_value()
  );
  // The reviewer lands on one line per section and opens what they came for.
  // Nothing here knows which branch carries their work, so nothing is expanded
  // on their behalf.
  let open = $state(
    untrack(() => (initiallyOpen ?? depth < 1) && !(Array.isArray(value) && value.length === 0))
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
    <details bind:open={previousOpen} class="min-w-0">
      <summary
        class="text-secondary hover:text-primary focus-visible:ring-ring flex min-h-8 w-fit cursor-pointer list-none items-center gap-1.5 rounded-sm text-xs focus-visible:ring-2 [&::-webkit-details-marker]:hidden"
      >
        <ChevronRight
          class="size-3.5 shrink-0 motion-safe:transition-transform motion-safe:duration-(--duration-quick) motion-safe:ease-(--ease-smooth-out) {previousOpen
            ? 'rotate-90'
            : ''}"
          aria-hidden="true"
        />
        {m.flow_run_review_previous_value()}
      </summary>
      {#if previousOpen}<div class="border-default mt-1 ml-1.5 border-l pb-2 pl-3">
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
    <!-- Two-up at the top level once there is room. The panel used to cap
         itself and leave the right third of the row empty while its
         textareas ran to 137 characters, about twice a comfortable measure.
         Splitting the columns spends the width on shorter lines rather than
         longer ones. Nested objects stay single-column: a grid inside a
         disclosure inside a grid stops being scannable. A lone field (a
         step's one list, say) takes the whole row instead of half of it. -->
    <div
      class={depth === 0 && shownFields.length > 1
        ? "grid min-w-0 gap-x-6 gap-y-3 @[1040px]/review-fields:grid-cols-2"
        : "flex min-w-0 flex-col gap-3"}
    >
      {#each shownFields as field (field.key)}
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
          initiallyOpen={depth === 0 && shownFields.length === 1 ? true : undefined}
          onChange={(next) => onChange(replaceReviewProperty(value, field.key, next))}
        />
      {/each}
    </div>
  {:else if kind === "array"}
    <div bind:this={itemList} class="flex min-w-0 flex-col">
      {#if !items.length}<p class="text-secondary py-1 text-sm">
          {m.flow_run_review_no_items()}
        </p>{/if}
      {#each items as item, index (index)}
        <div
          data-review-item
          class="border-default/60 flex min-w-0 items-start gap-2 border-b last:border-b-0"
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
              class="text-secondary hover:text-destructive mt-1 size-9 shrink-0"
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
          class="mt-3 min-h-10 self-start"
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
        class="text-primary hover:bg-hover-dimmer focus-visible:ring-ring flex min-h-11 cursor-pointer list-none items-start gap-2 rounded-sm py-2.5 text-sm focus-visible:ring-2 motion-safe:transition-colors motion-safe:duration-(--duration-micro) [&::-webkit-details-marker]:hidden"
      >
        <ChevronRight
          class="text-secondary mt-0.5 size-4 shrink-0 motion-safe:transition-transform motion-safe:duration-(--duration-quick) motion-safe:ease-(--ease-smooth-out) {open
            ? 'rotate-90'
            : ''}"
          aria-hidden="true"
        />
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
        {#if kind === "array" && items.length > 0}
          <Badge variant="secondary" class="shrink-0 tabular-nums" aria-hidden="true">
            {items.length}
          </Badge>
          <span class="sr-only"
            >{m.flow_run_review_collection_count({ label, count: items.length })}</span
          >
        {/if}
        {@render changedLabel()}
      </summary>
      {#if open}
        <div class="border-default ml-2 flex min-w-0 flex-col gap-3 border-l pb-3 pl-4">
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
          class="text-secondary hover:text-primary -my-1 size-8 shrink-0"
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
      {#if kind === "unsupported" && !readOnly}
        <p class="text-secondary max-w-prose text-sm leading-relaxed">
          {m.flow_run_review_unsupported_field()}
        </p>
      {/if}
      {@const structured = value !== null && typeof value === "object"}
      <!-- A value nobody can type into still reads as a value: the same inset
           geometry as an input, filled instead of outlined. The surface sits on
           an inline box so a short value does not become a wide empty panel. -->
      <p class="max-w-prose text-sm leading-relaxed">
        <span
          class="bg-hover-dimmer/60 text-primary inline-block max-w-full rounded-lg px-2.5 py-2 align-top [overflow-wrap:anywhere] whitespace-pre-wrap {structured
            ? 'max-h-64 w-full overflow-auto font-mono text-xs'
            : ''} {value === undefined || value === '' ? 'text-secondary italic' : ''}"
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
        </span>
      </p>
    {:else if kind === "string"}
      <Textarea
        {id}
        value={typeof value === "string" ? value : ""}
        {disabled}
        aria-describedby={helpOpen ? id + "-help" : undefined}
        autocomplete="off"
        class="min-h-10 max-w-[34rem] resize-none leading-relaxed"
        rows={1}
        oninput={(event) => onChange(event.currentTarget.value)}
      />
    {:else if kind === "enum" || kind === "boolean"}
      <Select.Root
        type="single"
        {disabled}
        value={choiceValue}
        onValueChange={(next) =>
          onChange(
            kind === "boolean"
              ? next === "true"
              : (choices.find((choice) => JSON.stringify(choice) === next) ?? "")
          )}
      >
        <Select.Trigger
          {id}
          class="min-h-10 w-full"
          aria-describedby={helpOpen ? id + "-help" : undefined}
        >
          <span class="truncate">{choiceLabel}</span>
        </Select.Trigger>
        <Select.Content>
          {#if kind === "boolean"}
            <Select.Item value="true" label={m.yes()}>{m.yes()}</Select.Item>
            <Select.Item value="false" label={m.no()}>{m.no()}</Select.Item>
          {:else}
            {#if typeof value === "string" && value !== "" && !choices.includes(value)}
              <!-- A stored value the contract no longer offers stays visible and unselectable. -->
              <Select.Item value={JSON.stringify(value)} label={value} disabled>
                {value}
              </Select.Item>
            {/if}
            {#each choices as choice (choice)}
              {@const optionLabel = reviewFieldLabel({}, choice) || m.flow_run_review_empty_value()}
              <Select.Item value={JSON.stringify(choice)} label={optionLabel}>
                {optionLabel}
              </Select.Item>
            {/each}
          {/if}
        </Select.Content>
      </Select.Root>
    {:else if kind === "number"}
      <Input
        {id}
        type="number"
        value={typeof value === "number" ? value : undefined}
        {disabled}
        step={schema.type === "integer" ? 1 : "any"}
        aria-describedby={helpOpen ? id + "-help" : undefined}
        autocomplete="off"
        class="min-h-10 max-w-[34rem]"
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
