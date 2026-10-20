<script lang="ts">
  import type { ConversationMessage } from "@eneo/eneo-js";
  import { Markdown } from "$lib/components/markdown/index.js";
  import { m } from "$lib/paraglide/messages";
  import { getMessageContext, setMessageContext } from "../../MessageContext.svelte";
  import { getChatService } from "../../ChatService.svelte";
  import { toolStepStatus } from "../../toolStepStatus";
  import { isAwaitingApproval } from "../../consultationApproval";
  import { isSkillActivation, serverDisplayName, toolDisplayName } from "../../internalToolLabels";
  import MessageEneoInfoBlob from "./MessageEneoInfoBlob.svelte";
  import ReasoningToolStep from "./ReasoningToolStep.svelte";
  import SkillActivationStep from "./SkillActivationStep.svelte";

  type Consultation = NonNullable<ConversationMessage["consultations"]>[number];
  let { consultation, streaming }: { consultation: Consultation; streaming: boolean } = $props();
  const parent = getMessageContext();
  const chat = getChatService();
  // Citation rendering uses the specialist's evidence and reply inside this
  // component, while the containing conversation retains its own context.
  setMessageContext({
    current: () => ({
      ...parent.current(),
      answer: consultation.answer,
      references: [],
      mcp_tool_references: consultation.references,
      tool_calls: consultation.tool_calls,
      consultations: []
    }),
    isLoading: () => streaming,
    isLast: parent.isLast
  });
  const labels: Record<Consultation["status"], () => string> = {
    running: m.chat_reasoning_working,
    awaiting_approval: m.group_consultation_approval,
    complete: m.chat_tool_status_done,
    denied: m.group_consultation_denied,
    timeout: m.group_consultation_timeout,
    cancelled: m.group_consultation_cancelled,
    incomplete: m.group_consultation_incomplete,
    failed: m.chat_tool_status_failed
  };
  // A consultation persisted as still running (a turn that died before its
  // steps were normalised) or carrying a status this client does not know is
  // shown as incomplete rather than as live work or a crash.
  const label = $derived.by(() => {
    const status = consultation.status;
    if (!streaming && (status === "running" || status === "awaiting_approval")) {
      return m.group_consultation_incomplete();
    }
    return (labels[status] ?? m.group_consultation_incomplete)();
  });
</script>

<details class="border-dimmer bg-primary rounded-lg border">
  <summary class="cursor-pointer px-3 py-2 text-sm focus-visible:ring-2">
    <span class="font-medium">{consultation.ordinal}. {consultation.assistant_name}</span>
    <span class="text-muted ml-2">{label}</span>
  </summary>
  <div class="border-dimmer flex flex-col gap-3 border-t px-3 py-3">
    <div>
      <p class="text-muted mb-1 text-xs font-medium">{m.group_consultation_question()}</p>
      <p class="whitespace-pre-wrap text-sm">{consultation.question}</p>
    </div>
    {#each consultation.tool_calls as step (step.step_id)}
      {@const status = toolStepStatus(
        isAwaitingApproval(consultation, step) ? "awaiting_approval" : step.result_status,
        step.approved === false,
        streaming
      )}
      {#if isSkillActivation(step)}
        <SkillActivationStep
          name={step.title ?? step.tool_name}
          {status}
          args={step.arguments ?? undefined}
        />
      {:else}
        <ReasoningToolStep
          toolName={toolDisplayName(
            step.tool_name,
            step.server_name,
            step.title,
            step.arguments ?? undefined,
            step.purpose,
            step.is_internal
          )}
          serverName={serverDisplayName(step.server_name, step.purpose, step.is_internal)}
          args={step.arguments ?? undefined}
          toolCallId={step.step_id}
          {status}
          onLoadResult={() => chat.getToolCallResult(step.step_id)}
        />
      {/if}
    {/each}
    {#if consultation.answer}
      <div>
        <p class="text-muted mb-1 text-xs font-medium">{m.group_consultation_answer()}</p>
        <Markdown source={consultation.answer} customRenderers={{ inref: MessageEneoInfoBlob }} />
      </div>
    {/if}
  </div>
</details>
