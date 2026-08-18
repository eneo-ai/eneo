<script lang="ts">
  /* Reasoning effort for the planning model. The options are named by the
     model itself; an empty list means this model takes no such setting and the
     control does not exist. */
  import * as Select from "$lib/components/ui/select/index.js";
  import { m } from "$lib/paraglide/messages";
  import Brain from "lucide-svelte/icons/brain";

  import { getAIBuilderService } from "./FlowAIBuilderService.svelte.ts";

  const DEFAULT_VALUE = "default";
  const EFFORT_PREFIX = "effort:";

  const service = getAIBuilderService();

  const options = $derived(service.effectiveModel?.reasoning_effort_options ?? []);
  const selected = $derived(service.selectedReasoningEffort);
  const value = $derived(selected === null ? DEFAULT_VALUE : `${EFFORT_PREFIX}${selected}`);
  const label = $derived(selected ? optionLabel(selected) : m.default_behavior());

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
    {value}
    disabled={!service.canSendMessage}
    onValueChange={(next) => {
      service.selectReasoningEffort(
        next === DEFAULT_VALUE ? null : next.slice(EFFORT_PREFIX.length)
      );
    }}
  >
    <Select.Trigger
      size="sm"
      class="composer-control"
      aria-label={`${m.reasoning_effort()}: ${label}`}
      title={m.reasoning_effort_tooltip()}
    >
      <Brain class="size-3.5" aria-hidden="true" />
      <span class="truncate">{label}</span>
    </Select.Trigger>
    <Select.Content align="start">
      <Select.Group>
        <Select.GroupHeading>{m.reasoning_effort()}</Select.GroupHeading>
        <Select.Item value={DEFAULT_VALUE} label={m.default_behavior()}>
          {m.default_behavior()}
        </Select.Item>
        {#each options as option (option)}
          <Select.Item value={`${EFFORT_PREFIX}${option}`} label={optionLabel(option)}>
            {optionLabel(option)}
          </Select.Item>
        {/each}
      </Select.Group>
    </Select.Content>
  </Select.Root>
{/if}
