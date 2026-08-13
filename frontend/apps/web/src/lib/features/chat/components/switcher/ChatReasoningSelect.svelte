<script lang="ts">
  import * as Select from "$lib/components/ui/select/index.js";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { selectEffectiveChatModel } from "$lib/features/chat/selectEffectiveChatModel";
  import { getModelKwargOptionLabel } from "$lib/features/ai-models/ModelKwargCapabilities";
  import { m } from "$lib/paraglide/messages";
  import Brain from "lucide-svelte/icons/brain";

  const DEFAULT_VALUE = "default";
  const VALUE_PREFIX = "reasoning:";

  const {
    state: { currentSpace },
    updateDefaultAssistant
  } = getSpacesManager();

  const assistant = $derived($currentSpace.default_assistant!);
  const effectiveConfig = $derived(assistant.effective_config);
  const selectedModel = $derived(
    selectEffectiveChatModel(
      assistant.completion_model,
      effectiveConfig,
      $currentSpace.completion_models
    ) ?? null
  );
  const capability = $derived(selectedModel?.supported_model_kwargs?.reasoning_effort);
  const options = $derived(
    capability?.supported && capability.control === "select" ? (capability.options ?? []) : []
  );
  const storedEffort = $derived(assistant.completion_model_kwargs?.reasoning_effort ?? null);
  const effectiveEffort = $derived.by(() => {
    if (storedEffort && options.includes(storedEffort)) return storedEffort;
    const policyDefault = effectiveConfig?.default_reasoning_effort;
    return policyDefault && options.includes(policyDefault) ? policyDefault : null;
  });
  const selectedValue = $derived(
    storedEffort && options.includes(storedEffort)
      ? `${VALUE_PREFIX}${storedEffort}`
      : DEFAULT_VALUE
  );

  function selectEffort(value: string) {
    const reasoningEffort = value.startsWith(VALUE_PREFIX)
      ? value.slice(VALUE_PREFIX.length)
      : null;
    updateDefaultAssistant({
      modelKwargs: { reasoning_effort: reasoningEffort }
    });
  }
</script>

{#if effectiveConfig?.reasoning_effort_user_configurable && options.length > 0}
  <Select.Root type="single" value={selectedValue} onValueChange={selectEffort}>
    <Select.Trigger
      size="sm"
      class="hover:bg-muted h-8 max-w-40 border-transparent bg-transparent px-2 font-medium shadow-none"
      aria-label={`${m.reasoning_effort()}: ${effectiveEffort ? getModelKwargOptionLabel(effectiveEffort) : m.default_behavior()}`}
      title={m.reasoning_effort_tooltip()}
    >
      <Brain class="size-3.5" aria-hidden="true" />
      <span class="hidden truncate sm:inline">
        {effectiveEffort ? getModelKwargOptionLabel(effectiveEffort) : m.default_behavior()}
      </span>
    </Select.Trigger>
    <Select.Content align="end">
      <Select.Group>
        <Select.GroupHeading>{m.reasoning_effort()}</Select.GroupHeading>
        <Select.Item value={DEFAULT_VALUE} label={m.governance_reasoning_organization_default()}>
          {m.governance_reasoning_organization_default()}
        </Select.Item>
        {#each options as option (option)}
          <Select.Item value={`${VALUE_PREFIX}${option}`} label={getModelKwargOptionLabel(option)}>
            {getModelKwargOptionLabel(option)}
          </Select.Item>
        {/each}
      </Select.Group>
    </Select.Content>
  </Select.Root>
{/if}
