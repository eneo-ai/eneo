<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Select } from "@intric/ui";
  import { behaviourList, type ModelBehaviour } from "../ModelBehaviours";
  import { m } from "$lib/paraglide/messages";

  export let value: ModelBehaviour;

  const behaviourLabels: Record<ModelBehaviour, string> = {
    creative: m.creative(),
    default: (m as any)["default"](),
    deterministic: m.deterministic(),
    custom: m.custom()
  };
</script>

<Select.Simple
  class="border-dimmer hover:bg-hover-dimmer relative w-full border-b px-4 py-4"
  bind:value
  options={behaviourList.map((behaviour) => ({
    value: behaviour,
    label: behaviourLabels[behaviour]
  }))}>{m.model_behaviour()}</Select.Simple
>
