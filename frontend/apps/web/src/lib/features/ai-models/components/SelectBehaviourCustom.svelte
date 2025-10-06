<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Input, Tooltip } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";

  export let kwargs: { temperature: number; top_p: number };
</script>

<div
  class="border-default bg-hover-dimmer hover:bg-hover-default relative -mt-1 w-full border-y px-4 py-4"
>
  <h3 class="pb-1 pl-3 font-medium">{m.model_configuration()}</h3>
  <div class="border-default bg-primary rounded-lg border shadow">
    <div
      class="hover:bg-hover-dimmer flex items-center gap-6 rounded-lg py-2 pr-2 pl-3"
      aria-labelledby="temperature_label"
    >
      <Tooltip
        text={m.temperature_tooltip()}
      >
        <p class="w-24" aria-label="Temperature setting" id="temperature_label">{m.temperature()}</p>
      </Tooltip>
      <Input.Slider bind:value={kwargs.temperature} max={2} min={0} step={0.01} />
      <Input.Number bind:value={kwargs.temperature} step={0.01} max={2} min={0} hiddenLabel={true}
      ></Input.Number>
    </div>
    <!-- For now we decided not to expose TOP P as a parameter to users -->
    <!-- <div class="border-b border-default"></div>
    <div
      class="flex items-center gap-6 rounded-lg py-2 pl-3 pr-2 hover:bg-hover-dimmer"
      aria-labelledby="top_p_setting"
    >
      <Tooltip
        text={"Diversity: A value between 0 and 1 (Default: 1)\nLower values restrict the number of potential completions the model can choose from."}
      >
        <p class="w-24" aria-label="Top P setting" id="top_p_label">{m.top_p()}</p>
      </Tooltip>
      <Input.Slider bind:value={kwargs.top_p} max={1} min={0} step={0.01} />
      <Input.Number step={0.01} max={1} min={0} bind:value={kwargs.top_p} labelClass="hidden" />
    </div> -->
  </div>
</div>
