<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Label } from "@intric/ui";
  import dayjs from "dayjs";
  import utc from "dayjs/plugin/utc";

  dayjs.extend(utc);
  
  import { m } from "$lib/paraglide/messages";

  export let prompt: {
    created_at?: string | null;
    description?: string | null;
    is_selected: boolean;
  };
</script>

<div class="flex items-center gap-4 px-3">
  <span>{dayjs(prompt.created_at).format("HH:mm")}</span>

  {#if prompt.is_selected}
    <Label.Single item={{ label: m.latest(), color: "green" }}></Label.Single>
  {/if}
</div>
