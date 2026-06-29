<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<!--
  Shared enable/disable list for space model availability. The settings routes
  own persistence; this component owns the canonical presentation so completion,
  embedding and transcription models expose provider context consistently.
-->

<script lang="ts" generics="T extends CompletionModel | EmbeddingModel | TranscriptionModel">
  import type { CompletionModel, EmbeddingModel, TranscriptionModel } from "@intric/intric-js";
  import { Input, Tooltip } from "@intric/ui";
  import { ChevronRight, Loader2, ShieldAlert } from "lucide-svelte";
  import { SvelteSet } from "svelte/reactivity";

  import * as ModelSelector from "$lib/components/ai-elements/model-selector/index.js";
  import { m } from "$lib/paraglide/messages";

  import { groupModelsByVendor, prettifyProviderType } from "../groupModels";
  import { sortModels } from "../sortModels";
  import ModelNameAndVendor from "./ModelNameAndVendor.svelte";
  import ModelStatusIcons, { getStatusIcons } from "./ModelStatusIcons.svelte";

  type SelectableModel<TModel> = TModel & {
    meets_security_classification?: boolean | null | undefined;
  };

  type LoadingLookup = {
    has(id: string): boolean;
  };

  type ModelDetail = {
    label: string;
    value: string;
    mono?: boolean;
  };

  type Props<TModel extends CompletionModel | EmbeddingModel | TranscriptionModel> = {
    models: SelectableModel<TModel>[];
    selectedIds: string[];
    loadingIds?: LoadingLookup;
    onToggle: (model: SelectableModel<TModel>) => void | Promise<void>;
  };

  let { models, selectedIds, loadingIds, onToggle }: Props<T> = $props();

  const sortedModels = $derived(sortModels([...models]));
  const modelGroups = $derived(groupModelsByVendor(sortedModels, m.model_group_other()));
  const selectedIdSet = $derived(new Set(selectedIds));
  const collapsedGroups = new SvelteSet<string>();

  function displayName(model: SelectableModel<T>) {
    return model.nickname ?? model.name;
  }

  function normalize(label: string | null | undefined) {
    return label?.trim().toLocaleLowerCase() ?? "";
  }

  function uniqueDetailParts(parts: ModelDetail[]) {
    const seen: string[] = [];
    return parts.flatMap((part) => {
      const value = part.value.trim();
      if (!value) return [];
      const key = normalize(value);
      if (seen.includes(key)) return [];
      seen.push(key);
      return [{ ...part, value }];
    });
  }

  function modelDetails(model: SelectableModel<T>, groupLabel: string) {
    const providerName = model.provider_name?.trim();
    const providerType = prettifyProviderType(model.provider_type);
    const underlyingName = model.name !== displayName(model) ? model.name : null;
    const details: ModelDetail[] = [];

    if (providerName) details.push({ label: m.provider_name(), value: providerName });
    if (providerType) details.push({ label: m.provider_type(), value: providerType });
    if (underlyingName) {
      details.push({ label: m.model_identifier(), value: underlyingName, mono: true });
    }

    return uniqueDetailParts(details).filter(
      (detail) => normalize(detail.value) !== normalize(groupLabel)
    );
  }

  function providerForLogo(model: SelectableModel<T>) {
    return model.org ?? model.provider_type ?? model.provider_name;
  }

  function groupCountLabel(count: number) {
    return count === 1
      ? m.provider_model_count_one({ count })
      : m.provider_model_count_other({ count });
  }

  function selectedCount(models: SelectableModel<T>[]) {
    return models.filter((model) => selectedIdSet.has(model.id)).length;
  }

  function hasStatusDetails(model: SelectableModel<T>) {
    return getStatusIcons(model).length > 0;
  }

  function toggleGroup(label: string) {
    if (collapsedGroups.has(label)) {
      collapsedGroups.delete(label);
    } else {
      collapsedGroups.add(label);
    }
  }

  function groupContentId(label: string) {
    return `model-provider-${label.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
  }
</script>

{#if modelGroups.length === 0}
  <div class="border-default text-muted rounded-xl border px-3 py-4 text-sm">
    {m.no_models_found()}
  </div>
{:else}
  <div class="flex flex-col gap-3">
    {#each modelGroups as group (group.label)}
      {@const enabledInGroup = selectedCount(group.models)}
      {@const isCollapsed = collapsedGroups.has(group.label)}
      <section class="border-default overflow-hidden rounded-xl border">
        <div
          class="border-default bg-surface-dimmer flex items-center justify-between gap-3 border-b px-3 py-2"
        >
          <button
            type="button"
            class="focus-visible:ring-stronger flex min-w-0 flex-1 items-center gap-2 rounded-md py-1 pr-2 text-left focus-visible:ring-2 focus-visible:outline-none"
            aria-expanded={!isCollapsed}
            aria-controls={groupContentId(group.label)}
            aria-label={`${isCollapsed ? m.show() : m.hide()} ${group.label}`}
            onclick={() => toggleGroup(group.label)}
          >
            <ChevronRight
              class="text-muted size-4 shrink-0 transition-transform {isCollapsed
                ? ''
                : 'rotate-90'}"
              aria-hidden="true"
            />
            <ModelSelector.Logo provider={group.label} />
            <div class="min-w-0">
              <h4 class="text-primary truncate text-sm leading-tight font-medium">{group.label}</h4>
              <p class="text-muted text-xs tabular-nums">
                {enabledInGroup}/{group.models.length} · {groupCountLabel(group.models.length)}
              </p>
            </div>
          </button>
        </div>

        <div id={groupContentId(group.label)} hidden={isCollapsed}>
          {#each group.models as model (model.id)}
            {@const meetsClassification = model.meets_security_classification ?? true}
            {@const isLoading = loadingIds?.has(model.id) ?? false}
            {@const isSelected = selectedIdSet.has(model.id)}
            {@const details = modelDetails(model, group.label)}
            <Tooltip
              text={meetsClassification
                ? undefined
                : m.model_does_not_meet_security_classification()}
            >
              <div
                aria-disabled={!meetsClassification || isLoading}
                class="border-default hover:bg-hover-dimmer border-b transition-colors last:border-b-0"
                class:opacity-60={!meetsClassification}
                class:opacity-80={isLoading}
              >
                <div class="py-3 pr-4 pl-3">
                  <Input.Switch
                    value={isSelected}
                    sideEffect={() => {
                      if (meetsClassification && !isLoading) {
                        onToggle(model);
                      }
                    }}
                  >
                    <div class="flex min-w-0 items-start gap-3">
                      <div
                        class="border-dimmer bg-surface-dimmer mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg border"
                      >
                        <ModelSelector.Logo provider={providerForLogo(model)} class="size-5" />
                      </div>

                      <div class="min-w-0 flex-1">
                        <div class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                          <ModelNameAndVendor {model} descriptionMode="non-tabbable" />
                          {#if hasStatusDetails(model)}
                            <ModelStatusIcons {model} showCost={false} />
                          {/if}
                          {#if !meetsClassification}
                            <ShieldAlert
                              class="text-warning-stronger size-4 shrink-0"
                              aria-hidden="true"
                            />
                          {/if}
                          {#if isLoading}
                            <Loader2
                              class="text-muted size-4 shrink-0 animate-spin"
                              aria-hidden="true"
                            />
                          {/if}
                        </div>

                        {#if details.length > 0}
                          <dl class="mt-1.5 flex min-w-0 flex-wrap gap-1.5">
                            {#each details as detail (`${detail.label}-${detail.value}`)}
                              <div
                                class="border-dimmer bg-surface-dimmer inline-flex max-w-full min-w-0 items-center gap-1.5 rounded-md border px-1.5 py-0.5 text-xs"
                              >
                                <dt class="text-muted shrink-0">{detail.label}</dt>
                                <dd
                                  class="text-secondary min-w-0 truncate"
                                  class:font-mono={detail.mono}
                                >
                                  {detail.value}
                                </dd>
                              </div>
                            {/each}
                          </dl>
                        {/if}
                      </div>
                    </div>
                  </Input.Switch>
                </div>
              </div>
            </Tooltip>
          {/each}
        </div>
      </section>
    {/each}
  </div>
{/if}
