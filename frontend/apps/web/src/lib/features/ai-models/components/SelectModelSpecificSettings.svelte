<script lang="ts">
  import { IconQuestionMark } from "@eneo/icons/question-mark";
  import { Input, Tooltip } from "@eneo/ui";
  import type { ModelKwargs } from "@eneo/eneo-js";
  import { m } from "$lib/paraglide/messages";
  import {
    getModelKwargCapability,
    getModelSpecificKwargNames,
    type CompletionModelWithSupportedKwargs,
    type ModelKwargName
  } from "../ModelKwargCapabilities";

  export let kwArgs: ModelKwargs;
  export let selectedModel: CompletionModelWithSupportedKwargs | null = null;

  type NumericKwargName = Extract<
    ModelKwargName,
    "top_p" | "presence_penalty" | "frequency_penalty" | "top_k"
  >;
  type SelectKwargName = Extract<ModelKwargName, "reasoning_effort" | "verbosity">;

  const numericKwargNames = [
    "top_p",
    "presence_penalty",
    "frequency_penalty",
    "top_k"
  ] as const satisfies readonly NumericKwargName[];

  const defaultNumericValues: Record<NumericKwargName, number> = {
    top_p: 1,
    presence_penalty: 0,
    frequency_penalty: 0,
    top_k: 40
  };

  const defaultMaximumValues: Record<NumericKwargName, number> = {
    top_p: 1,
    presence_penalty: 2,
    frequency_penalty: 2,
    top_k: 100
  };

  let numericValues: Record<NumericKwargName, number> = { ...defaultNumericValues };
  let useDefaultNumeric: Record<NumericKwargName, boolean> = {
    top_p: true,
    presence_penalty: true,
    frequency_penalty: true,
    top_k: true
  };
  let selectValues: Partial<Record<SelectKwargName, string>> = {};
  let lastSyncedStateKey = "";

  $: modelSpecificKwargNames = getModelSpecificKwargNames(selectedModel);
  $: syncLocalState(kwArgs, selectedModel);

  function isNumericKwargName(kwargName: ModelKwargName): kwargName is NumericKwargName {
    return numericKwargNames.includes(kwargName as NumericKwargName);
  }

  function isSelectKwargName(kwargName: ModelKwargName): kwargName is SelectKwargName {
    return kwargName === "reasoning_effort" || kwargName === "verbosity";
  }

  function syncLocalState(
    currentKwArgs: ModelKwargs | null | undefined,
    currentModel: CompletionModelWithSupportedKwargs | null
  ) {
    const nextStateKey = JSON.stringify({
      modelId: currentModel?.id ?? currentModel?.name ?? null,
      kwargs: currentKwArgs ?? {}
    });
    if (nextStateKey === lastSyncedStateKey) return;

    for (const kwargName of numericKwargNames) {
      const currentValue = currentKwArgs?.[kwargName];
      useDefaultNumeric[kwargName] = currentValue == null;
      numericValues[kwargName] =
        typeof currentValue === "number" ? currentValue : defaultNumericValues[kwargName];
    }
    selectValues.reasoning_effort = currentKwArgs?.reasoning_effort ?? "";
    selectValues.verbosity = currentKwArgs?.verbosity ?? "";
    lastSyncedStateKey = nextStateKey;
  }

  function setNumericDefault(kwargName: NumericKwargName, useDefault: boolean) {
    useDefaultNumeric[kwargName] = useDefault;
    kwArgs = {
      ...kwArgs,
      [kwargName]: useDefault ? null : numericValues[kwargName]
    };
  }

  function setNumericKwarg(kwargName: NumericKwargName, value = numericValues[kwargName]) {
    numericValues[kwargName] = value;
    if (useDefaultNumeric[kwargName]) return;

    kwArgs = {
      ...kwArgs,
      [kwargName]: value
    };
  }

  function setSelectKwarg(kwargName: SelectKwargName, value: string) {
    selectValues[kwargName] = value;
    kwArgs = {
      ...kwArgs,
      [kwargName]: value || null
    };
  }

  function getNumericMinimum(kwargName: NumericKwargName) {
    return getModelKwargCapability(selectedModel, kwargName)?.minimum ?? 0;
  }

  function getNumericMaximum(kwargName: NumericKwargName) {
    return (
      getModelKwargCapability(selectedModel, kwargName)?.maximum ?? defaultMaximumValues[kwargName]
    );
  }

  function getNumericStep(kwargName: NumericKwargName) {
    return getModelKwargCapability(selectedModel, kwargName)?.step ?? 1;
  }

  function getSelectOptions(kwargName: SelectKwargName) {
    return getModelKwargCapability(selectedModel, kwargName)?.options ?? [];
  }

  function getKwargLabel(kwargName: ModelKwargName) {
    switch (kwargName) {
      case "reasoning_effort":
        return m.reasoning_effort();
      case "verbosity":
        return m.verbosity();
      case "top_p":
        return m.top_p();
      case "presence_penalty":
        return m.presence_penalty();
      case "frequency_penalty":
        return m.frequency_penalty();
      case "top_k":
        return m.top_k();
      default:
        return kwargName;
    }
  }

  function getKwargTooltip(kwargName: ModelKwargName) {
    switch (kwargName) {
      case "reasoning_effort":
        return m.reasoning_effort_tooltip();
      case "verbosity":
        return m.verbosity_tooltip();
      case "top_p":
        return m.top_p_tooltip();
      case "presence_penalty":
        return m.presence_penalty_tooltip();
      case "frequency_penalty":
        return m.frequency_penalty_tooltip();
      case "top_k":
        return m.top_k_tooltip();
      default:
        return "";
    }
  }

  function getOptionLabel(option: string) {
    switch (option) {
      case "none":
        return m.none();
      case "low":
        return m.parameter_option_low();
      case "medium":
        return m.parameter_option_medium();
      case "high":
        return m.parameter_option_high();
      default:
        return option;
    }
  }
</script>

{#each modelSpecificKwargNames as kwargName (kwargName)}
  <div
    class="border-default hover:bg-hover-stronger flex min-h-[4.125rem] items-center justify-between gap-8 border-b px-4 py-3"
  >
    <div class="flex items-center gap-2">
      <p class="w-36" aria-label={getKwargLabel(kwargName)}>{getKwargLabel(kwargName)}</p>
      <Tooltip text={getKwargTooltip(kwargName)}>
        <IconQuestionMark class="text-muted hover:text-primary" />
      </Tooltip>
    </div>

    {#if isSelectKwargName(kwargName)}
      <select
        value={selectValues[kwargName] ?? ""}
        on:change={(event) => setSelectKwarg(kwargName, event.currentTarget.value)}
        class="border-default bg-primary ring-default rounded border px-3 py-2 focus:ring-2"
      >
        <option value="">{m.default_behavior()}</option>
        {#each getSelectOptions(kwargName) as option (option)}
          <option value={option}>{getOptionLabel(option)}</option>
        {/each}
      </select>
    {:else if isNumericKwargName(kwargName)}
      <div class="flex flex-1 items-center justify-end gap-4">
        <label class="flex items-center gap-2 text-sm whitespace-nowrap">
          <input
            type="checkbox"
            checked={useDefaultNumeric[kwargName]}
            on:change={(event) => setNumericDefault(kwargName, event.currentTarget.checked)}
          />
          {m.default_behavior()}
        </label>

        {#if !useDefaultNumeric[kwargName]}
          <Input.Slider
            bind:value={numericValues[kwargName]}
            min={getNumericMinimum(kwargName)}
            max={getNumericMaximum(kwargName)}
            step={getNumericStep(kwargName)}
            onInput={(value) => setNumericKwarg(kwargName, value)}
          />
          <Input.Number
            bind:value={numericValues[kwargName]}
            min={getNumericMinimum(kwargName)}
            max={getNumericMaximum(kwargName)}
            step={getNumericStep(kwargName)}
            hiddenLabel={true}
            on:input={() => setNumericKwarg(kwargName)}
          />
        {/if}
      </div>
    {/if}
  </div>
{/each}
