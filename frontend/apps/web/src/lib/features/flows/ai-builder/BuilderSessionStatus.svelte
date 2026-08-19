<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Button } from "$lib/components/ui/button/index.js";
  import IconCheck from "@lucide/svelte/icons/check";
  import IconAlertTriangle from "@lucide/svelte/icons/triangle-alert";
  import IconMessageSquare from "@lucide/svelte/icons/message-square";
  import { getAIBuilderService } from "./FlowAIBuilderService.svelte.ts";

  /**
   * Whether the draft is safe, and the way into the conversation. It sits on
   * the title row where the design puts it, so the phase rail is the only
   * thing between the title and the work.
   */
  const service = getAIBuilderService();

  // The server records the message before it works on it, so a recorded turn
  // that failed is not lost. Only a request that never got an answer leaves
  // the draft genuinely uncertain.
  const savingProblem = $derived(service.error?.code === "network");
</script>

<div class="flex min-w-0 flex-1 items-center gap-3">
  {#if savingProblem}
    <span
      class="text-warning-stronger inline-flex shrink-0 items-center gap-1.5 text-xs font-semibold max-sm:sr-only"
      title={m.ai_builder_saved_state_problem_title()}
      role="status"
    >
      <IconAlertTriangle class="size-3.5" aria-hidden="true" />
      {m.ai_builder_saved_state_problem()}
    </span>
  {:else if service.hasSession && service.messages.length > 0}
    <span
      class="text-secondary inline-flex shrink-0 items-center gap-1.5 text-xs max-sm:sr-only"
      title={m.ai_builder_saved_state_title()}
    >
      <span
        class="bg-positive-dimmer text-positive-stronger inline-flex size-[0.9375rem] items-center justify-center rounded-full"
        aria-hidden="true"
      >
        <IconCheck class="size-2.5" strokeWidth={3.5} />
      </span>
      {m.ai_builder_saved_state_auto()}
    </span>
  {:else}
    <span class="text-secondary shrink-0 text-xs max-sm:sr-only">
      {m.ai_builder_saved_state_new()}
    </span>
  {/if}

  <Button
    variant="outline"
    size="sm"
    class="ml-auto shrink-0 gap-1.5"
    aria-pressed={service.conversationOpen}
    aria-label={m.ai_builder_conversation_button_aria({
      count: String(service.visibleMessageCount)
    })}
    title={m.ai_builder_conversation_button_title()}
    onclick={() => service.toggleConversation()}
  >
    <IconMessageSquare class="size-3.5" />
    <span class="max-sm:sr-only">{m.ai_builder_conversation_button()}</span>
    <span
      class="bg-tertiary text-secondary inline-flex h-[1.125rem] min-w-[1.125rem] items-center justify-center rounded-full px-1.5 text-[0.6875rem] font-bold"
    >
      {service.visibleMessageCount}
    </span>
  </Button>
</div>
