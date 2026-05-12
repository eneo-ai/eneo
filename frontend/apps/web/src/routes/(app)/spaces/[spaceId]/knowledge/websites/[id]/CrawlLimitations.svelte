<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { m } from "$lib/paraglide/messages";
  import { Info } from "lucide-svelte";
</script>

<div class="border-dimmer hidden border-b py-3 pr-3 lg:block">
  <Alert.Root class="label-info border-label-default bg-label-dimmer text-label-stronger">
    <Info class="text-label-stronger" aria-hidden="true" />
    <Alert.Title class="text-label-stronger">{m.limitations()}</Alert.Title>
    <Alert.Description class="text-label-stronger/85">
      {m.crawl_limitations_description()}
    </Alert.Description>
  </Alert.Root>
</div>
