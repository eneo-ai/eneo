<script lang="ts">
  import * as Select from "$lib/components/ui/select/index.js";
  import { m } from "$lib/paraglide/messages";
  import Brain from "lucide-svelte/icons/brain";
  import { getAIBuilderService } from "./FlowAIBuilderService.svelte.ts";

  const DEFAULT_REASONING_VALUE = "default";
  const REASONING_VALUE_PREFIX = "reasoning:";
  const service = getAIBuilderService();

  const selectedModel = $derived(
    service.availableModels.find((model) => model.id === service.selectedModelId) ?? null
  );
  const options = $derived(selectedModel?.reasoning_effort_options ?? []);
  const selectedValue = $derived(
    service.selectedReasoningEffort === null
      ? DEFAULT_REASONING_VALUE
      : `${REASONING_VALUE_PREFIX}${service.selectedReasoningEffort}`
  );
  const selectedLabel = $derived(
    service.selectedReasoningEffort
      ? optionLabel(service.selectedReasoningEffort)
      : m.default_behavior()
  );

  function optionLabel(option: string): string {
    switch (option) {
      case "none":
        return m.none();
      case "minimal":
        return m.ai_builder_reasoning_minimal();
      case "low":
        return m.parameter_option_low();
      case "medium":
        return m.parameter_option_medium();
      case "high":
        return m.parameter_option_high();
      case "xhigh":
        return m.ai_builder_reasoning_extra_high();
      case "max":
        return m.ai_builder_reasoning_max();
      default:
        return option.replaceAll("_", " ");
    }
  }
</script>

{#if options.length > 0}
  <Select.Root
    type="single"
    value={selectedValue}
    onValueChange={(value) => {
      if (value === DEFAULT_REASONING_VALUE) {
        service.selectReasoningEffort(null);
        return;
      }
      if (value.startsWith(REASONING_VALUE_PREFIX)) {
        service.selectReasoningEffort(value.slice(REASONING_VALUE_PREFIX.length));
      }
    }}
  >
    <Select.Trigger
      size="sm"
      class="hover:bg-muted h-7 max-w-40 border-transparent bg-transparent px-2 font-medium shadow-none max-sm:h-11"
      aria-label={`${m.reasoning_effort()}: ${selectedLabel}`}
      title={m.reasoning_effort_tooltip()}
    >
      <Brain class="size-3.5" aria-hidden="true" />
      <span class="truncate">{selectedLabel}</span>
    </Select.Trigger>
    <Select.Content align="start">
      <Select.Group>
        <Select.GroupHeading>{m.reasoning_effort()}</Select.GroupHeading>
        <Select.Item value={DEFAULT_REASONING_VALUE} label={m.default_behavior()}>
          {m.default_behavior()}
        </Select.Item>
        {#each options as option (option)}
          <Select.Item value={`${REASONING_VALUE_PREFIX}${option}`} label={optionLabel(option)}>
            {optionLabel(option)}
          </Select.Item>
        {/each}
      </Select.Group>
    </Select.Content>
  </Select.Root>
{/if}
