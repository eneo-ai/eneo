<script lang="ts">
  import { Button } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";
  import { getChatService } from "../../ChatService.svelte";
  import type { ElicitationState } from "../../ChatService.svelte";

  let { elicitation }: { elicitation: ElicitationState } = $props();

  const chat = getChatService();
  let answer = $state("");

  // Interactive only while pending AND still the live elicitation; once answered
  // (or for a reloaded message) we render the persisted question + answer.
  const isActive = $derived(
    elicitation.status === "pending" &&
      chat.pendingElicitation?.elicitationId === elicitation.elicitationId
  );

  function submitAnswer() {
    if (!answer.trim()) return;
    const value = answer;
    answer = "";
    chat.submitElicitation("accept", value);
  }
</script>

{#if isActive}
  <div class="border-default bg-secondary flex flex-col gap-2 border-t px-3 py-2.5 text-sm">
    <p class="whitespace-pre-line">{elicitation.message}</p>
    {#if elicitation.answerField}
      {#if elicitation.suggestions.length > 0}
        <div class="flex flex-wrap gap-1.5">
          {#each elicitation.suggestions as suggestion (suggestion)}
            <button
              type="button"
              class="border-default hover:bg-hover-default rounded-full border px-3 py-1"
              onclick={() => chat.submitElicitation("accept", suggestion)}
            >
              {suggestion}
            </button>
          {/each}
        </div>
      {/if}
      <div class="flex gap-2">
        <input
          type="text"
          bind:value={answer}
          placeholder={m.elicitation_answer_placeholder()}
          class="border-default bg-primary flex-1 rounded-lg border px-3 py-1.5"
          onkeydown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              submitAnswer();
            }
          }}
        />
        <Button variant="primary" disabled={!answer.trim()} onclick={submitAnswer}>
          {m.send()}
        </Button>
        <Button variant="outlined" onclick={() => chat.submitElicitation("decline")}>
          {m.decline()}
        </Button>
      </div>
    {:else}
      <div class="flex gap-2">
        <Button variant="primary" onclick={() => chat.submitElicitation("accept")}>
          {m.confirm()}
        </Button>
        <Button variant="outlined" onclick={() => chat.submitElicitation("decline")}>
          {m.decline()}
        </Button>
      </div>
    {/if}
  </div>
{:else if elicitation.status !== "pending"}
  <!-- Persisted outcome, shown after answering and on history -->
  <div class="text-secondary border-t px-3 py-2 text-sm">
    <p class="whitespace-pre-line">{elicitation.message}</p>
    <p class="text-primary mt-0.5 font-medium">
      {#if elicitation.status === "declined"}
        {m.decline()}
      {:else}
        {elicitation.answer ?? m.confirm()}
      {/if}
    </p>
  </div>
{/if}
