<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<!--
  Form fields for one in-progress model draft. Renders the right subset of
  fields based on `modelType`:
    - completion   → token budgets + capability checkboxes
    - embedding    → family + dimensions + max input
    - transcription → name + display name + hosting + classification
-->

<script lang="ts">
  import { onMount, tick } from "svelte";
  import { Loader2, ListPlus } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";
  import { getEneo } from "$lib/core/Eneo";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Checkbox } from "$lib/components/ui/checkbox/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import * as Field from "$lib/components/ui/field/index.js";

  import HostingSelect from "$lib/features/ai-models/hosting/HostingSelect.svelte";
  import { getSecurityContext } from "$lib/features/security-classifications/SecurityContext";
  import SelectSecurityClassification from "$lib/features/security-classifications/components/SelectSecurityClassification.svelte";

  import HelpTooltip from "../../components/HelpTooltip.svelte";
  import {
    MAX_COST_INPUT,
    perMillionFromTokenCost,
    type ModelDraftState,
    type ModelType
  } from "./draft";

  let {
    draft = $bindable(),
    modelType,
    isSelfHosted = false,
    /** Canonical provider type (e.g. "openai", "azure"). Threaded into the
     *  "Lookup defaults" call so LiteLLM rows are disambiguated correctly —
     *  Azure-served gpt-4o picks up azure/gpt-4o prices, not openai/gpt-4o.
     *  Optional only because the edit dialog may not always know the
     *  provider context; without it, the backend falls back to bare-name
     *  resolution with unambiguous-prefix matching. */
    providerType,
    /** Show the bottom "Add another model" form-submit button. Set false
     *  when the form is hosted in a dialog that supplies its own footer. */
    showAddAnotherButton = true,
    canAdd = false,
    showAddAnotherHint = false,
    /** When set, the model identifier becomes read-only — only completion
     *  models allow editing it on existing records, and even there it's
     *  effectively a rename of the underlying litellm name. */
    nameReadOnly = false
  }: {
    draft: ModelDraftState;
    modelType: ModelType;
    isSelfHosted?: boolean;
    providerType?: string;
    showAddAnotherButton?: boolean;
    canAdd?: boolean;
    showAddAnotherHint?: boolean;
    nameReadOnly?: boolean;
  } = $props();

  const eneo = getEneo();
  const classifications = getSecurityContext().security_classifications;

  const FAMILY_OPTIONS = [
    { value: "openai", label: "OpenAI (Standard)" },
    { value: "e5", label: "E5 (HuggingFace)" }
  ];

  let isLookingUpDefaults = $state(false);

  onMount(async () => {
    await tick();
    document.getElementById("model-name")?.focus();
  });

  async function lookupDefaults() {
    if (!draft.name.trim()) return;
    isLookingUpDefaults = true;
    try {
      // The hand-maintained client typings don't include the cost fields yet,
      // so we read them through an explicit cast.
      const result = (await eneo.modelProviders.getModelDefaults(
        draft.name.trim(),
        providerType
      )) as unknown as {
        found: boolean;
        max_input_tokens?: number | null;
        max_output_tokens?: number | null;
        supports_vision?: boolean;
        supports_reasoning?: boolean;
        supports_function_calling?: boolean;
        input_cost_per_token?: number | null;
        output_cost_per_token?: number | null;
        cost_per_minute?: number | null;
      };
      if (!result.found) {
        toast.info(m.reset_to_defaults_not_found({ model: draft.name.trim() }));
        return;
      }
      if (modelType === "completion") {
        if (result.max_input_tokens != null)
          draft.maxInputTokensStr = String(result.max_input_tokens);
        if (result.max_output_tokens != null)
          draft.maxOutputTokensStr = String(result.max_output_tokens);
        draft.vision = result.supports_vision ?? false;
        draft.reasoning = result.supports_reasoning ?? false;
        draft.supportsToolCalling = result.supports_function_calling ?? false;
      } else if (modelType === "embedding") {
        if (result.max_input_tokens != null) draft.maxInputStr = String(result.max_input_tokens);
      }
      if (modelType === "transcription") {
        if (result.cost_per_minute != null) {
          draft.costPerMinuteStr = String(result.cost_per_minute);
        }
      } else {
        // Backend returns USD/token (LiteLLM's native unit); we display
        // and store the form value as USD per 1M tokens for readability.
        if (result.input_cost_per_token != null) {
          draft.inputCostPerTokenStr = perMillionFromTokenCost(result.input_cost_per_token);
        }
        if (result.output_cost_per_token != null) {
          draft.outputCostPerTokenStr = perMillionFromTokenCost(result.output_cost_per_token);
        }
      }
      toast.success(m.reset_to_defaults_success());
    } catch {
      toast.info(m.reset_to_defaults_not_found({ model: draft.name.trim() }));
    } finally {
      isLookingUpDefaults = false;
    }
  }

  function familyLabel(value: string): string {
    return FAMILY_OPTIONS.find((o) => o.value === value)?.label ?? value;
  }
</script>

<div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
  <Field.Field>
    <Field.Label for="model-name" class="flex items-center gap-1.5">
      {m.model_identifier()}
      <HelpTooltip text={m.model_identifier_help()} />
    </Field.Label>
    <Input
      id="model-name"
      bind:value={draft.name}
      readonly={nameReadOnly}
      placeholder={modelType === "completion"
        ? m.model_identifier_placeholder_completion()
        : modelType === "embedding"
          ? m.model_identifier_placeholder_embedding()
          : m.model_identifier_placeholder_transcription()}
    />
    {#if draft.name.trim() && !isSelfHosted}
      <button
        type="button"
        class="text-accent-default hover:text-accent-stronger flex items-center gap-1 self-start text-xs underline underline-offset-2 transition-colors disabled:cursor-not-allowed disabled:opacity-50"
        disabled={isLookingUpDefaults}
        onclick={lookupDefaults}
      >
        {#if isLookingUpDefaults}
          <Loader2 class="size-3 animate-spin" aria-hidden="true" />
        {/if}
        {m.lookup_defaults()}
      </button>
    {/if}
  </Field.Field>

  <Field.Field>
    <Field.Label for="display-name">{m.display_name()}</Field.Label>
    <Input
      id="display-name"
      bind:value={draft.displayName}
      placeholder={m.display_name_placeholder_completion()}
    />
  </Field.Field>
</div>

{#if modelType === "completion"}
  <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
    <Field.Field>
      <Field.Label for="max-input-tokens" class="flex items-center gap-1.5">
        {m.max_input_tokens()}
        <HelpTooltip text={m.max_input_tokens_help()} />
      </Field.Label>
      <Input
        id="max-input-tokens"
        type="number"
        bind:value={draft.maxInputTokensStr}
        placeholder={m.max_input_tokens()}
        min="1024"
        max="10000000"
      />
      <Field.Description>{m.token_reference_input()}</Field.Description>
    </Field.Field>

    <Field.Field>
      <Field.Label for="max-output-tokens" class="flex items-center gap-1.5">
        {m.max_output_tokens()}
        <HelpTooltip text={m.max_output_tokens_help()} />
      </Field.Label>
      <Input
        id="max-output-tokens"
        type="number"
        bind:value={draft.maxOutputTokensStr}
        placeholder={m.max_output_tokens()}
        min="1"
        max="10000000"
      />
      <Field.Description>{m.token_reference_output()}</Field.Description>
    </Field.Field>
  </div>

  <fieldset class="border-0 p-0">
    <legend class="sr-only">{m.model_details()}</legend>
    <div class="flex flex-wrap items-center gap-x-6 gap-y-3">
      <Field.Field orientation="horizontal" class="w-fit">
        <Checkbox id="cap-vision" bind:checked={draft.vision} />
        <Field.Label for="cap-vision" class="flex items-center gap-1">
          {m.vision_support()}
          <HelpTooltip text={m.vision_help()} />
        </Field.Label>
      </Field.Field>
      <Field.Field orientation="horizontal" class="w-fit">
        <Checkbox id="cap-reasoning" bind:checked={draft.reasoning} />
        <Field.Label for="cap-reasoning" class="flex items-center gap-1">
          {m.reasoning_support()}
          <HelpTooltip text={m.reasoning_help()} />
        </Field.Label>
      </Field.Field>
      <Field.Field orientation="horizontal" class="w-fit">
        <Checkbox id="cap-tools" bind:checked={draft.supportsToolCalling} />
        <Field.Label for="cap-tools" class="flex items-center gap-1">
          {m.tool_calling_support()}
          <HelpTooltip text={m.tool_calling_help()} />
        </Field.Label>
      </Field.Field>
    </div>
  </fieldset>
{/if}

{#if modelType === "embedding"}
  <div class="grid grid-cols-1 gap-4 sm:grid-cols-3">
    <Field.Field>
      <Field.Label for="model-family" class="flex items-center gap-1.5">
        {m.model_family()}
        <HelpTooltip text={m.model_family_help()} />
      </Field.Label>
      <Select.Root type="single" bind:value={draft.family}>
        <Select.Trigger id="model-family" class="w-full">
          <span data-slot="select-value">{familyLabel(draft.family)}</span>
        </Select.Trigger>
        <Select.Content>
          {#each FAMILY_OPTIONS as option (option.value)}
            <Select.Item value={option.value} label={option.label}>{option.label}</Select.Item>
          {/each}
        </Select.Content>
      </Select.Root>
    </Field.Field>

    <Field.Field>
      <Field.Label for="dimensions" class="flex items-center gap-1.5">
        {m.dimensions()}
        <HelpTooltip text={m.dimensions_help()} />
      </Field.Label>
      <Input id="dimensions" type="number" bind:value={draft.dimensionsStr} placeholder="1536" />
    </Field.Field>

    <Field.Field>
      <Field.Label for="max-input">{m.max_input_tokens()}</Field.Label>
      <Input id="max-input" type="number" bind:value={draft.maxInputStr} placeholder="8191" />
    </Field.Field>
  </div>
{/if}

<Field.Field>
  <Field.Label for="hosting">{m.hosting_region()}</Field.Label>
  <HostingSelect id="hosting" bind:value={draft.hosting} />
</Field.Field>

<!--
  Cost. Stored in USD; left empty when LiteLLM has no data and the admin
  doesn't want to track it. Token-based for completion+embedding, per-minute
  of audio for transcription.
-->
{#if modelType === "transcription"}
  <Field.Field>
    <Field.Label for="cost-per-minute" class="flex items-center gap-1.5">
      {m.cost_per_minute()}
      <HelpTooltip text={m.cost_per_minute_help()} />
    </Field.Label>
    <Input
      id="cost-per-minute"
      type="number"
      step="0.000001"
      min="0"
      max={MAX_COST_INPUT}
      bind:value={draft.costPerMinuteStr}
      placeholder={m.cost_input_placeholder()}
    />
    <Field.Description>{m.cost_currency_hint()}</Field.Description>
  </Field.Field>
{:else}
  <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
    <Field.Field>
      <Field.Label for="input-cost" class="flex items-center gap-1.5">
        {m.input_cost_per_token()}
        <HelpTooltip text={m.input_cost_per_token_help()} />
      </Field.Label>
      <Input
        id="input-cost"
        type="number"
        step="0.01"
        min="0"
        max={MAX_COST_INPUT}
        bind:value={draft.inputCostPerTokenStr}
        placeholder={m.cost_input_placeholder()}
      />
      <Field.Description>{m.cost_currency_hint()}</Field.Description>
    </Field.Field>
    <Field.Field>
      <Field.Label for="output-cost" class="flex items-center gap-1.5">
        {m.output_cost_per_token()}
        <HelpTooltip text={m.output_cost_per_token_help()} />
      </Field.Label>
      <Input
        id="output-cost"
        type="number"
        step="0.01"
        min="0"
        max={MAX_COST_INPUT}
        bind:value={draft.outputCostPerTokenStr}
        placeholder={m.cost_input_placeholder()}
      />
    </Field.Field>
  </div>
{/if}

<!-- Free-text description so admins can guide end-users on when to pick this model. -->
<Field.Field>
  <Field.Label for="model-description">{m.model_description()}</Field.Label>
  <textarea
    id="model-description"
    bind:value={draft.description}
    placeholder={m.model_description_placeholder()}
    rows="3"
    maxlength="500"
    class="border-input focus-visible:border-ring focus-visible:ring-ring/50 placeholder:text-muted-foreground w-full rounded-lg border bg-transparent px-2.5 py-1.5 text-sm transition-colors outline-none focus-visible:ring-3"
  ></textarea>
  <Field.Description>{m.model_description_hint()}</Field.Description>
</Field.Field>

{#if classifications.length > 0}
  <Field.Field>
    <Field.Label>{m.security()}</Field.Label>
    <div class="border-border max-h-48 overflow-y-auto rounded-md border">
      <SelectSecurityClassification {classifications} bind:value={draft.securityClassification} />
    </div>
  </Field.Field>
{/if}

{#if showAddAnotherButton}
  <div class="border-border/40 mt-2 flex items-center gap-3 border-t pt-4">
    <Button type="submit" variant="ghost" disabled={!canAdd}>
      <ListPlus aria-hidden="true" />
      {m.add_another_model()}
    </Button>
    {#if showAddAnotherHint}
      <span class="text-muted-foreground text-xs">{m.or_click_finish_directly()}</span>
    {/if}
  </div>
{/if}
