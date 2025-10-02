<script lang="ts">
  import { Button } from "@intric/ui";
  import { pushState } from "$app/navigation";
  import ConversationView from "$lib/features/chat/components/conversation/ConversationView.svelte";
  import { fade, fly } from "svelte/transition";
  import { quadInOut } from "svelte/easing";
  import { initChatService } from "$lib/features/chat/ChatService.svelte.js";
  import { m } from "$lib/paraglide/messages";

  let { data } = $props();

  const chat = initChatService(data);

  $effect(() => {
    // Re-init if rout param changes
    chat.init(data);
  });
</script>

<svelte:head>
  <title>Eneo.ai – Dashboard – {chat.partner.name}</title>
</svelte:head>

<div class="outer bg-primary flex w-full flex-col">
  <div
    class="bg-primary sticky top-0 flex items-center justify-between px-3.5 py-3 backdrop-blur-md"
    in:fade={{ duration: 50 }}
  >
    <a href="/dashboard" class="flex max-w-[calc(100%_-_7rem)] flex-grow items-center rounded-lg">
      <span
        class="border-default hover:bg-hover-dimmer flex h-8 w-8 items-center justify-center rounded-lg border"
        >←</span
      >
      <h1
        in:fly|global={{
          x: -5,
          duration: parent ? 300 : 0,
          easing: quadInOut,
          opacity: 0.3
        }}
        class="truncate px-3 py-1 text-xl font-extrabold"
      >
        {chat.partner.name}
      </h1>
    </a>
    <Button
      variant="primary"
      on:click={() => {
        chat.newConversation();
        pushState(`/dashboard/${chat.partner.id}?tab=chat`, {
          conversation: undefined,
          tab: "chat"
        });
      }}
      class="!rounded-lg !border-b-2 !border-[var(--color-ui-blue-700)] !px-5 !py-1"
      >{m.new_chat()}
    </Button>
  </div>

  <ConversationView></ConversationView>
</div>

<style>
  @media (display-mode: standalone) {
    .outer {
      background-color: var(--background-primary);
      overflow-y: auto;
      margin: 0 0.5rem;
      border-radius: 1rem;
      box-shadow: 0 4px 10px 0px rgba(0, 0, 0, 0.1);
      max-height: 100%;
    }
  }

  @container (min-width: 1000px) {
    .outer {
      margin: 1.5rem;
      border-radius: 1rem;
      box-shadow: 0 4px 10px 0px rgba(0, 0, 0, 0.1);
      max-width: 1400px;
      overflow: hidden;
    }
  }
</style>
