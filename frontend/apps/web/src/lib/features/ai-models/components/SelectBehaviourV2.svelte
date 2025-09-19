<script lang="ts">
  import {
    behaviourList,
    getBehaviour,
    getKwargs,
    type ModelBehaviour,
    type ModelKwArgs
  } from "../ModelBehaviours";
  import { createSelect } from "@melt-ui/svelte";
  import { IconChevronDown } from "@intric/icons/chevron-down";
  import { IconCheck } from "@intric/icons/check";
  import { IconQuestionMark } from "@intric/icons/question-mark";
  import { Input, Tooltip } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";

  export let kwArgs: ModelKwArgs;
  export let isDisabled: boolean;

  export let selectedModel: any = null; // CompletionModel from the parent
  export let aria: AriaProps = { "aria-label": m.select_model_behaviour() };

  const behaviourLabels: Record<ModelBehaviour, string> = {
    creative: m.creative(),
    default: (m as any)["default"](),
    deterministic: m.deterministic(),
    custom: m.custom()
  };

  // Check if model has custom parameters that should override behavior presets
  // For reasoning models, disable behavior controls as they have model-specific parameters
  $: hasModelSpecificParams = selectedModel?.reasoning || selectedModel?.litellm_model_name;
  $: isDisabledDueToModelParams = !!hasModelSpecificParams;
  $: finalIsDisabled = isDisabled || isDisabledDueToModelParams;

  const {
    elements: { trigger, menu, option },
    helpers: { isSelected },
    states: { selected }
  } = createSelect<ModelBehaviour>({
    defaultSelected: { value: getBehaviour(kwArgs) },
    positioning: {
      placement: "bottom",
      fitViewport: true,
      sameWidth: true
    },
    portal: null,
    onSelectedChange: ({ next }) => {
      const behaviorKwargs = next?.value ? getKwargs(next.value) : getKwargs("default");

      if (behaviorKwargs) {
        // Preserve all existing fields while only updating the behavior-relevant ones
        kwArgs = {
          ...kwArgs,
          ...behaviorKwargs
        };
      } else {
        // For custom behavior, preserve current kwargs if already custom, otherwise set defaults
        const customArgs = getBehaviour(kwArgs) === "custom" ? kwArgs : {
          ...kwArgs,
          temperature: 1,
          top_p: null
        };
        kwArgs = customArgs;
      }
      return next;
    }
  });

  // This function will only be called on direct user input of custom temperature
  // If the selected value is not a named value, it will set the Kwargs
  // This can't be a declarative statement with $: as it would fire in too many situations
  let customTemp: number = 1;
  function maybeSetKwArgsCustom() {
    const args = { temperature: customTemp, top_p: null };
    if (getBehaviour(args) === "custom") {
      // Preserve all existing fields while only updating temperature and top_p
      kwArgs = {
        ...kwArgs,
        ...args
      };
    }
  }

  function watchChanges(currentKwArgs: ModelKwArgs) {
    const behaviour = getBehaviour(currentKwArgs);

    if ($selected?.value !== behaviour) {
      $selected = { value: behaviour };
    }

    if (
      behaviour === "custom" &&
      currentKwArgs.temperature &&
      currentKwArgs.temperature !== customTemp
    ) {
      customTemp = currentKwArgs.temperature;
    }
  }

  $: watchChanges(kwArgs);

  // Track previous disabled state to only reset on transition
  let previousDisabledState = finalIsDisabled;
  $: {
    // Only reset when transitioning from enabled to disabled
    if (finalIsDisabled && !previousDisabledState) {
      $selected = { value: "default" };
      const defaultKwargs = getKwargs("default") || { temperature: null, top_p: null };
      // Preserve all existing fields while only updating the behavior-relevant ones
      kwArgs = {
        ...kwArgs,
        ...defaultKwargs
      };
    }
    previousDisabledState = finalIsDisabled;
  }
</script>

<button
  {...$trigger}
  {...aria}
  use:trigger
  disabled={finalIsDisabled}
  class:hover:cursor-default={finalIsDisabled}
  class:text-secondary={finalIsDisabled}
  class="border-default hover:bg-hover-default flex h-16 items-center justify-between border-b px-4"
>
  <span class="capitalize">{$selected?.value ? behaviourLabels[$selected?.value] : m.no_behaviour_found()}</span>
  <IconChevronDown />
</button>

<div
  class="border-stronger bg-primary z-20 flex flex-col overflow-y-auto rounded-lg border shadow-xl"
  {...$menu}
  use:menu
>
  <div
    class="bg-frosted-glass-secondary border-default sticky top-0 border-b px-4 py-2 font-mono text-sm"
  >
    {m.select_model_behaviour()}
  </div>
  {#each behaviourList as behavior (behavior)}
    <div
      class="border-default hover:bg-hover-stronger flex min-h-16 items-center justify-between border-b px-4 hover:cursor-pointer"
      {...$option({ value: behavior })}
      use:option
    >
      <span class="capitalize">
        {behaviourLabels[behavior]}
      </span>
      <div class="check {$isSelected(behavior) ? 'block' : 'hidden'}">
        <IconCheck class="text-positive-default" />
      </div>
    </div>
  {/each}
</div>

{#if $selected?.value === "custom"}
  <div
    class="border-default hover:bg-hover-stronger flex h-[4.125rem] items-center justify-between gap-8 border-b px-4"
  >
    <div class="flex items-center gap-2">
      <p class="w-24" aria-label="Temperature setting" id="temperature_label">{m.temperature()}</p>
      <Tooltip
        text={m.temperature_tooltip()}
      >
        <IconQuestionMark class="text-muted hover:text-primary" />
      </Tooltip>
    </div>
    <Input.Slider
      bind:value={customTemp}
      max={2}
      min={0}
      step={0.01}
      onInput={maybeSetKwArgsCustom}
    />
    <Input.Number
      onInput={maybeSetKwArgsCustom}
      bind:value={customTemp}
      step={0.01}
      max={2}
      min={0}
      hiddenLabel={true}
    ></Input.Number>
  </div>
{/if}

{#if isDisabledDueToModelParams}
  <p
    class="label-info border-label-default bg-label-dimmer text-label-stronger mt-2.5 rounded-md border px-2 py-1 text-sm"
  >
    <span class="font-bold">Info:&nbsp;</span>This model uses model-specific parameters instead of behavior presets.
  </p>
{:else if isDisabled}
  <p
    class="label-warning border-label-default bg-label-dimmer text-label-stronger mt-2.5 rounded-md border px-2 py-1 text-sm"
  >
    <span class="font-bold">{m.warning()}:&nbsp;</span>{m.temperature_not_available()}
  </p>
{/if}

<style lang="postcss">
  @reference "@intric/ui/styles";
  div[data-highlighted] {
    @apply bg-hover-default;
  }

  /* div[data-selected] { } */

  div[data-disabled] {
    @apply opacity-30 hover:bg-transparent;
  }
</style>
