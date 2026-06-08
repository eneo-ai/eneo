<script lang="ts">
  import ElicitationPrompt from "./ElicitationPrompt.svelte";
  import { getChatService } from "../../ChatService.svelte";
  import type { ElicitationState } from "../../ChatService.svelte";

  let { elicitation }: { elicitation: ElicitationState } = $props();

  const chat = getChatService();

  // Interactive only while pending AND still the live elicitation; once answered
  // (or for a reloaded message) we render the persisted question + answer.
  const isActive = $derived(
    elicitation.status === "pending" &&
      chat.pendingElicitation?.elicitationId === elicitation.elicitationId
  );
</script>

<ElicitationPrompt
  variant="inline"
  {isActive}
  message={elicitation.message}
  answerField={elicitation.answerField}
  suggestions={elicitation.suggestions}
  options={elicitation.options}
  multiple={elicitation.multiple}
  status={elicitation.status}
  answer={elicitation.answer}
/>
