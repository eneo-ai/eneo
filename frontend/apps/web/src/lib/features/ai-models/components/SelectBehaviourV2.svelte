<script lang="ts">
  import {
    behaviourList,
    getBehaviour,
    getKwargs,
    type ModelBehaviour,
    type ModelKwArgs
  } from "../ModelBehaviours";
  import { IconChevronDown } from "@eneo/icons/chevron-down";
  import { IconQuestionMark } from "@eneo/icons/question-mark";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { Select as SelectPrimitive } from "bits-ui";
  import { Slider } from "$lib/components/ui/slider/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { m } from "$lib/paraglide/messages";
  import {
    shouldShowModelSpecificParametersInfo,
    supportsBehaviorPresets,
    type CompletionModelWithSupportedKwargs
  } from "../ModelKwargCapabilities";

  export let kwArgs: ModelKwArgs;
  export let isDisabled: boolean;

  export let selectedModel: CompletionModelWithSupportedKwargs | null = null;
  export let aria: AriaProps = { "aria-label": m.select_model_behaviour() };

  const behaviourLabels: Record<ModelBehaviour, string> = {
    creative: m.creative(),
    default: m.default_behavior(),
    deterministic: m.deterministic(),
    custom: m.custom()
  };

  $: selectedModelHasCapabilityContract = selectedModel?.supported_model_kwargs != null;
  $: shouldShowModelSpecificInfo = shouldShowModelSpecificParametersInfo(selectedModel);
  $: isDisabledDueToUnsupportedTemperature =
    selectedModelHasCapabilityContract && !supportsBehaviorPresets(selectedModel);
  $: finalIsDisabled = isDisabled || isDisabledDueToUnsupportedTemperature;

  let selectedBehaviour: ModelBehaviour = getBehaviour(kwArgs);

  function selectBehaviour(next: ModelBehaviour) {
    selectedBehaviour = next;
    const behaviorKwargs = getKwargs(next);

    if (behaviorKwargs) {
      kwArgs = {
        ...kwArgs,
        ...behaviorKwargs
      };
    } else {
      const customArgs =
        getBehaviour(kwArgs) === "custom"
          ? kwArgs
          : {
              ...kwArgs,
              temperature: 1
            };
      kwArgs = customArgs;
    }
  }

  let customTemp: number = 1;
  function maybeSetKwArgsCustom() {
    const args = { temperature: customTemp };
    if (getBehaviour(args) === "custom") {
      kwArgs = {
        ...kwArgs,
        ...args
      };
    }
  }

  function watchChanges(currentKwArgs: ModelKwArgs) {
    const behaviour = getBehaviour(currentKwArgs);

    if (selectedBehaviour !== behaviour) {
      selectedBehaviour = behaviour;
    }

    if (
      behaviour === "custom" &&
      currentKwArgs.temperature != null &&
      currentKwArgs.temperature !== customTemp
    ) {
      customTemp = currentKwArgs.temperature;
    }
  }

  $: watchChanges(kwArgs);

  let previousDisabledState = finalIsDisabled;
  $: {
    if (finalIsDisabled && !previousDisabledState) {
      selectedBehaviour = "default";
      const defaultKwargs = getKwargs("default") || { temperature: null };
      kwArgs = {
        ...kwArgs,
        ...defaultKwargs
      };
    }
    previousDisabledState = finalIsDisabled;
  }
</script>

<Select.Root
  type="single"
  value={selectedBehaviour}
  onValueChange={(next) => selectBehaviour(next as ModelBehaviour)}
  disabled={finalIsDisabled}
>
  <SelectPrimitive.Trigger>
    {#snippet child({ props })}
      <button
        {...props}
        {...aria}
        class:hover:cursor-default={finalIsDisabled}
        class:text-secondary={finalIsDisabled}
        class="border-default hover:bg-hover-default flex h-16 w-full items-center justify-between border-b px-4"
      >
        <span class="capitalize">{behaviourLabels[selectedBehaviour]}</span>
        <IconChevronDown />
      </button>
    {/snippet}
  </SelectPrimitive.Trigger>
  <Select.Content>
    <Select.Group>
      <Select.GroupHeading>{m.select_model_behaviour()}</Select.GroupHeading>
      {#each behaviourList as behavior (behavior)}
        <Select.Item value={behavior} label={behaviourLabels[behavior]} class="capitalize">
          {behaviourLabels[behavior]}
        </Select.Item>
      {/each}
    </Select.Group>
  </Select.Content>
</Select.Root>

{#if selectedBehaviour === "custom"}
  <div
    class="border-default hover:bg-hover-stronger flex h-[4.125rem] items-center justify-between gap-8 border-b px-4"
  >
    <div class="flex items-center gap-2">
      <p class="w-24">{m.temperature()}</p>
      <Tooltip.Root>
        <Tooltip.Trigger class="cursor-default">
          <IconQuestionMark class="text-muted hover:text-primary" />
          <span class="sr-only">{m.temperature_tooltip()}</span>
        </Tooltip.Trigger>
        <Tooltip.Content>{m.temperature_tooltip()}</Tooltip.Content>
      </Tooltip.Root>
    </div>
    <Slider
      type="single"
      bind:value={customTemp}
      max={2}
      min={0}
      step={0.01}
      onValueChange={maybeSetKwArgsCustom}
      aria-label={m.model_temperature_setting()}
    />
    <Input
      type="number"
      bind:value={customTemp}
      step={0.01}
      max={2}
      min={0}
      aria-label={m.model_temperature_setting()}
      class="w-24 shrink-0 text-center"
      oninput={() => {
        if (typeof customTemp !== "number") return;
        customTemp = Math.min(2, Math.max(0, customTemp));
        maybeSetKwArgsCustom();
      }}
    />
  </div>
{/if}

{#if shouldShowModelSpecificInfo}
  <p
    class="label-info border-label-default bg-label-dimmer text-label-stronger mt-2.5 rounded-md border px-2 py-1 text-sm"
  >
    <span class="font-bold">{m.model_info_label()}:&nbsp;</span
    >{m.model_uses_specific_parameters_info()}
  </p>
{:else if isDisabled || isDisabledDueToUnsupportedTemperature}
  <p
    class="label-warning border-label-default bg-label-dimmer text-label-stronger mt-2.5 rounded-md border px-2 py-1 text-sm"
  >
    <span class="font-bold">{m.warning()}:&nbsp;</span>{m.temperature_not_available()}
  </p>
{/if}
