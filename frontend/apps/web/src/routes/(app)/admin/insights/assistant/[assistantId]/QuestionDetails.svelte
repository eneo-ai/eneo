<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { getEneo } from "$lib/core/Eneo";
  import CodeBlock from "$lib/components/CodeBlock.svelte";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
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

  const eneo = getEneo();

  let loggingDetails = "";
  let copied = false;

  let loadingLog = false;
  async function loadLog() {
    if (!loggingDetails) {
      loadingLog = true;
      try {
        const loaded = message.id ? await eneo.logging.get({ id: message.id }) : message;
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

  let isOpen = false;
</script>

<Dialog.Root bind:open={isOpen}>
  <Dialog.Trigger onclick={loadLog}>
    {#snippet child({ props })}
      <Button
        {...props}
        variant="ghost"
        class="-ml-1.5 h-auto justify-start py-1 text-left whitespace-normal"
        >{message.question === "" ? m.untitled() : message.question}
      </Button>
    {/snippet}
  </Dialog.Trigger>
  <Dialog.Content class={dialogLayout.content("medium")} closeLabel={m.close()}>
    <Dialog.Header class={dialogLayout.header}>
      <Dialog.Title>{m.details_for({ question: message.question || m.untitled() })}</Dialog.Title>
      <Dialog.Description class="sr-only"
        >{m.insights_details_for_message({ id: message.id ?? "" })}</Dialog.Description
      >
    </Dialog.Header>
    <div class={dialogLayout.body}>
      {#if loadingLog}
        {m.loading()}
      {:else}
        <div class="border-default bg-secondary mb-4 rounded-md border px-3 py-2 text-sm">
          <div><strong>{m.question()}:</strong> {message.question || m.untitled()}</div>
          {#if message.created_at}
            <div class="text-secondary"><strong>{m.created()}:</strong> {message.created_at}</div>
          {/if}
          {#if message.session_id}
            <div class="text-secondary">
              <strong>{m.insights_session_id()}</strong>
              {message.session_id}
            </div>
          {/if}
        </div>
        <div class="mb-3 flex justify-end">
          <Button variant="outline" onclick={copyLog}>
            {copied ? m.copied() : m.copy()}
          </Button>
        </div>
        <CodeBlock source={loggingDetails} class="max-h-[60vh]" />
      {/if}
    </div>
    <Dialog.Footer class={dialogLayout.footer}>
      <Dialog.Close class={buttonVariants()}>{m.done()}</Dialog.Close>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
