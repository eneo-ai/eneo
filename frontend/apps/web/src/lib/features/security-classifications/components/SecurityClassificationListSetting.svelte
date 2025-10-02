<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import { flip } from "svelte/animate";
  import { getSecurityClassificationService } from "../SecurityClassificationsService.svelte";
  import SecurityClassificationCreateDialog from "./SecurityClassificationCreateDialog.svelte";
  import SecurityClassificationActions from "./SecurityClassificationActions.svelte";
  import { IconLockClosed } from "@intric/icons/lock-closed";
  import { IconLockOpen } from "@intric/icons/lock-open";
  import { m } from "$lib/paraglide/messages";

  const security = getSecurityClassificationService();
</script>

<Settings.Row
  fullWidth
  title={m.classifications()}
  description={m.classifications_description()}
>
  <div slot="toolbar">
    <SecurityClassificationCreateDialog></SecurityClassificationCreateDialog>
  </div>

  <div class="relative pl-2">
    <div class="border-default absolute top-2 bottom-2 left-9 z-0 border-l"></div>
    <div
      class="border-strongest bg-primary relative z-0 mb-4 flex w-fit items-center gap-2 rounded-full border px-4 py-2 font-mono text-sm shadow-sm"
    >
      <IconLockClosed></IconLockClosed> {m.highest_security()}
    </div>
    {#if security.classifications.length > 0}
      <table class=" w-full">
        <tbody>
          {#each security.classifications as classification (classification.id)}
            <tr class="group" animate:flip={{ duration: 200 }}>
              <td class="px-5 py-7 text-center align-top">
                <span
                  class="border-strongest bg-primary relative block h-4 w-4 rounded-full border shadow-sm"
                ></span>
              </td>
              <td
                class="border-default group-hover:bg-hover-dimmer w-fit rounded-l-lg px-4 py-6 align-top font-bold"
              >
                {classification.name}
              </td>
              <td class="border-default group-hover:bg-hover-dimmer w-[55%] px-4 py-6">
                {classification.description}
              </td>
              <td
                class=" border-default group-hover:bg-hover-dimmer w-12 rounded-r-lg px-4 py-6 align-top"
              >
                <SecurityClassificationActions {classification}></SecurityClassificationActions>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    {:else}
      <div class="text-muted flex h-20 items-center justify-center">
        {m.no_security_classifications()}
      </div>
    {/if}
    <div
      class="border-strongest bg-primary relative z-0 mt-4 flex w-fit items-center gap-2 rounded-full border px-4 py-2 font-mono text-sm shadow-sm"
    >
      <IconLockOpen></IconLockOpen> {m.lowest_security()}
    </div>
  </div>
</Settings.Row>
