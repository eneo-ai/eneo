<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { getIntric } from "$lib/core/Intric";
  import type { AssistantResponse } from "@intric/intric-js";
  import { Button, CodeBlock, Dialog } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";

  export let message: AssistantResponse;

  const intric = getIntric();

  let loggingDetails: string;

  let loadingLog = false;
  async function loadLog() {
    if (!loggingDetails && message.id) {
      loadingLog = true;
      try {
        loggingDetails = JSON.stringify(await intric.logging.get({ id: message.id }), null, 2);
      } catch (e: unknown) {
        loggingDetails = JSON.stringify(message, null, 2);
      }
      loadingLog = false;
    }
    return true;
  }

  let isOpen: Dialog.OpenState;
</script>

<Dialog.Root bind:isOpen>
  <Button
    class="-ml-1.5"
    on:click={() => {
      $isOpen = true;
      loadLog();
    }}
    >{message.question === "" ? m.untitled() : message.question}
  </Button>
  <Dialog.Content width="medium">
    <Dialog.Title>{m.details_for({ question: message.question })}</Dialog.Title>
    <Dialog.Description hidden>Details for message with id {message.id}</Dialog.Description>
    {#if loadingLog}
      {m.loading()}
    {:else}
      <CodeBlock source={loggingDetails} class="max-h-[60vh]" />
    {/if}
    <Dialog.Controls let:close>
      <Button variant="primary" is={close}>{m.done()}</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
