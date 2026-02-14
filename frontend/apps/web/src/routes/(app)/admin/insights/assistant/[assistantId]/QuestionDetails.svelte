<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { getIntric } from "$lib/core/Intric";
  import { Button, CodeBlock, Dialog } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";

  type InsightMessage = {
    id?: string;
    question?: string;
    answer?: string;
    created_at?: string;
    updated_at?: string;
    session_id?: string;
    [key: string]: unknown;
  };

  export let message: InsightMessage;

  const intric = getIntric();

  let loggingDetails = "";
  let copied = false;

  let loadingLog = false;
  async function loadLog() {
    if (!loggingDetails) {
      loadingLog = true;
      try {
        const loaded = message.id ? await intric.logging.get({ id: message.id }) : message;
        loggingDetails = JSON.stringify(loaded, null, 2);
      } catch (e: unknown) {
        loggingDetails = JSON.stringify(message, null, 2);
      }
      loadingLog = false;
    }
    return true;
  }

  async function copyLog() {
    if (!loggingDetails || !navigator?.clipboard) return;
    await navigator.clipboard.writeText(loggingDetails);
    copied = true;
    setTimeout(() => {
      copied = false;
    }, 1200);
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
    <Dialog.Title>{m.details_for({ question: message.question || m.untitled() })}</Dialog.Title>
    <Dialog.Description hidden>Details for message with id {message.id}</Dialog.Description>
    {#if loadingLog}
      {m.loading()}
    {:else}
      <div class="border-default bg-secondary mb-4 rounded-md border px-3 py-2 text-sm">
        <div><strong>{m.question()}:</strong> {message.question || m.untitled()}</div>
        {#if message.created_at}
          <div class="text-secondary"><strong>{m.created()}:</strong> {message.created_at}</div>
        {/if}
        {#if message.session_id}
          <div class="text-secondary"><strong>Session ID:</strong> {message.session_id}</div>
        {/if}
      </div>
      <div class="mb-3 flex justify-end">
        <Button variant="outlined" on:click={copyLog}>
          {copied ? m.copied() : m.copy()}
        </Button>
      </div>
      <CodeBlock source={loggingDetails} class="max-h-[60vh]" />
    {/if}
    <Dialog.Controls let:close>
      <Button variant="primary" is={close}>{m.done()}</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
