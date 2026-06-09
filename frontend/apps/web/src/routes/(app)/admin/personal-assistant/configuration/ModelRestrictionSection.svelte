<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Label } from "$lib/components/ui/label/index.js";
  import * as RadioGroup from "$lib/components/ui/radio-group/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { m } from "$lib/paraglide/messages";
  import { IconCPU } from "@intric/icons/CPU";
  import { AlertCircle } from "lucide-svelte";
  import PolicySection from "./PolicySection.svelte";

  type ModelSelection = { selected: boolean; isDefault: boolean };
  type CompletionModel = {
    id: string;
    provider_id?: string | null;
    nickname?: string | null;
    name: string;
  };
  type ReadableMap<K, V> = {
    entries(): IterableIterator<[K, V]>;
    get(key: K): V | undefined;
  };
  type ReadableSet<T> = {
    has(value: T): boolean;
    size: number;
  };

  type Props = {
    modelsEnabled: boolean;
    modelsByProvider: ReadableMap<string | null, CompletionModel[]>;
    modelSelections: ReadableMap<string, ModelSelection>;
    providerSelections: ReadableSet<string>;
    effectiveModelIds: ReadableSet<string>;
    defaultModelId: string | null;
    modelsSummary: string;
    defaultValid: boolean;
    badgeVariant: (enabled: boolean, valid: boolean) => "default" | "outline" | "destructive";
    providerName: (providerId: string | null) => string;
    setSingleDefault: (modelId: string) => void;
    toggleModelSelected: (modelId: string, selected: boolean) => void;
    toggleProvider: (providerId: string, selected: boolean) => void;
  };

  let {
    modelsEnabled = $bindable(),
    modelsByProvider,
    modelSelections,
    providerSelections,
    effectiveModelIds,
    defaultModelId,
    modelsSummary,
    defaultValid,
    badgeVariant,
    providerName,
    setSingleDefault,
    toggleModelSelected,
    toggleProvider
  }: Props = $props();
</script>

<PolicySection
  id="models"
  title={m.governance_models_heading()}
  description={m.governance_models_section_desc()}
  summary={modelsSummary}
  summaryVariant={badgeVariant(modelsEnabled, effectiveModelIds.size > 0 && defaultValid)}
>
  {#snippet icon()}
    <IconCPU class="h-5 w-5" />
  {/snippet}

  <div class="flex items-center justify-between gap-3">
    <Label for="models-enabled" class="text-sm font-medium">
      {m.governance_models_toggle_label()}
    </Label>
    <Switch id="models-enabled" bind:checked={modelsEnabled} aria-describedby="models-help" />
  </div>

  {#if modelsEnabled}
    <p id="models-help" class="text-secondary text-sm">
      {m.governance_models_help_enabled()}
    </p>
    <!-- One default model across all providers, so a single radio group wraps every table. -->
    <RadioGroup.Root
      bind:value={() => defaultModelId ?? "", (v) => v && setSingleDefault(v)}
      class="gap-3"
    >
      {#each Array.from(modelsByProvider.entries()) as [pid, providerModels] (pid ?? "_unprovided")}
        {@const isProviderSelected = pid !== null && providerSelections.has(pid)}
        <fieldset class="border-default overflow-hidden rounded-lg border">
          <legend class="sr-only">{providerName(pid)}</legend>
          <div
            class="bg-secondary border-default flex items-center justify-between gap-3 border-b px-4 py-3"
          >
            <div class="flex items-center gap-3">
              {#if pid !== null}
                <Switch
                  checked={isProviderSelected}
                  onCheckedChange={(v) => toggleProvider(pid, v)}
                  aria-label={m.governance_provider_allow_all_aria({
                    provider: providerName(pid)
                  })}
                />
              {:else}
                <div class="w-8" aria-hidden="true"></div>
              {/if}
              <div>
                <div class="text-primary text-sm font-semibold">
                  {providerName(pid)}
                </div>
                <div class="text-secondary text-xs">
                  {#if isProviderSelected}
                    {m.governance_provider_all_allowed()}
                  {:else if pid === null}
                    {m.governance_provider_no_provider_desc()}
                  {:else if providerModels.length === 1}
                    {m.governance_provider_model_count_one({ count: providerModels.length })}
                  {:else}
                    {m.governance_provider_model_count_other({ count: providerModels.length })}
                  {/if}
                </div>
              </div>
            </div>
          </div>
          <table
            class="w-full text-sm"
            aria-label={m.governance_models_table_aria({ provider: providerName(pid) })}
          >
            <thead class="sr-only">
              <tr>
                <th scope="col">{m.governance_col_allow()}</th>
                <th scope="col">{m.governance_col_model()}</th>
                <th scope="col">{m.governance_col_default()}</th>
              </tr>
            </thead>
            <tbody>
              {#each providerModels as model (model.id)}
                {@const sel = modelSelections.get(model.id)}
                {@const includedViaProvider = isProviderSelected}
                {@const effectivelySelected = includedViaProvider || (sel?.selected ?? false)}
                <tr class="border-default border-t {includedViaProvider ? 'bg-secondary/30' : ''}">
                  <td class="w-14 px-4 py-2.5">
                    <Switch
                      checked={effectivelySelected}
                      disabled={includedViaProvider}
                      onCheckedChange={(v) => toggleModelSelected(model.id, v)}
                      aria-label={m.governance_model_allow_aria({
                        name: model.nickname ?? model.name
                      })}
                    />
                  </td>
                  <td class="px-4 py-2.5">
                    <span class={includedViaProvider ? "text-secondary" : ""}>
                      {model.nickname ?? model.name}
                    </span>
                    {#if includedViaProvider}
                      <span class="text-tertiary ml-1.5 text-xs">{m.governance_via_provider()}</span
                      >
                    {/if}
                  </td>
                  <td class="w-20 px-4 py-2.5">
                    <div class="flex items-center gap-2">
                      <RadioGroup.Item
                        value={model.id}
                        id={`default-${model.id}`}
                        disabled={!effectivelySelected}
                        aria-label={m.governance_model_set_default_aria({
                          name: model.nickname ?? model.name
                        })}
                      />
                      <Label for={`default-${model.id}`} class="text-secondary text-xs">
                        {m.governance_default_label()}
                      </Label>
                    </div>
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </fieldset>
      {/each}
    </RadioGroup.Root>
    {#if effectiveModelIds.size === 0}
      <p class="text-destructive flex items-center gap-2 text-sm" role="alert">
        <AlertCircle class="h-4 w-4 shrink-0" aria-hidden="true" />
        {m.governance_models_error_none()}
      </p>
    {:else if !defaultValid}
      <p class="text-destructive flex items-center gap-2 text-sm" role="alert">
        <AlertCircle class="h-4 w-4 shrink-0" aria-hidden="true" />
        {m.governance_models_error_default_invalid()}
      </p>
    {/if}
  {:else}
    <p id="models-help" class="text-secondary text-sm">
      {m.governance_models_help_disabled()}
    </p>
  {/if}
</PolicySection>
