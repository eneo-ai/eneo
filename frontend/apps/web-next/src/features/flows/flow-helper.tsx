import { IconButton } from "@astryxdesign/core/IconButton";
import { useQueryClient } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { useTranslations } from "use-intl";
import type { ChatReferences } from "@/features/chat/chat-references";
import type { HelperAdapter } from "@/features/helper/helper-adapter";
import { useSpace } from "@/features/spaces/use-space";
import { flowChangeCardFor } from "./chat/flow-change-card";
import { flowRunCardFor } from "./chat/flow-run-card";
import { isFlowsToolCall } from "./chat/flows-tool-call";
import { flowHelperApi, flowKeys, type FlowPublic } from "./flows-api";
import { flowErrorText } from "./runs/run-messages";

/** The flow chat's refusal when the space has no model with tools to answer. */
const NO_MODEL = "flow_authoring_chat_no_model";

/**
 * "Optimera flödet": puts a prepared request in the composer that asks the
 * chat to review the flow with its suggestions tool and propose
 * improvements. The person reads it, edits it if they like, and sends it;
 * nothing is sent from here.
 */
export function OptimizeFlowButton({ onAskChat }: { onAskChat: (text: string) => void }) {
  const t = useTranslations();
  return (
    <IconButton
      label={t("flow_suggestions_optimize")}
      tooltip={t("flow_suggestions_optimize")}
      variant="ghost"
      size="sm"
      icon={<Sparkles aria-hidden className="size-4" />}
      onClick={() => onAskChat(t("flow_suggestions_optimize_request"))}
    />
  );
}

/**
 * The helper panel's adapter for a flow. The chat needs edit access; a mode
 * change is fenced on the draft revision on screen; a published flow has no
 * draft to change, so Redigera is off and the panel says why. The chat's
 * pills are the flow's steps and values, a run it starts shows as a run
 * card and a change it makes as the steps it touched; its title row offers
 * "Optimera flödet" once the flow has a step.
 */
export function useFlowHelper({
  flow,
  references,
  onAskChat,
  onRefused,
  onFlowMayHaveChanged
}: {
  flow: FlowPublic;
  /** The flow's references (`useFlowChatReferences`), which the page also inserts through. */
  references: ChatReferences;
  /**
   * Puts a prepared request ("Optimera flödet") into the composer at the
   * caret, never sending it nor changing the mode; absent until the
   * composer is on the page.
   */
  onAskChat?: (text: string) => void;
  /** A refused change of the chat, shown with the page's other refusals. */
  onRefused: (error: unknown, title: string) => void;
  /** A tool of the chat finished, or an answer ended: the flow may have changed. */
  onFlowMayHaveChanged: () => void;
}): HelperAdapter {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const { routeId } = useSpace();
  return {
    api: flowHelperApi(flow.id),
    unavailable: flow.permissions.can_edit ? null : t("flows_chat_no_access"),
    texts: {
      heading: t("flows_chat_heading"),
      partnerName: t("flows_chat_partner_name"),
      partnerDescription: {
        ask: t("flows_chat_partner_description_ask"),
        edit: t("flows_chat_partner_description")
      },
      placeholder: {
        ask: t("flows_chat_placeholder_ask"),
        edit: t("flows_chat_placeholder_edit")
      },
      composerLabelEdit: t("flows_chat_composer_label_edit"),
      modeDescription: {
        ask: t("flows_chat_mode_ask_description"),
        edit: t("flows_chat_mode_edit_description")
      },
      editingOn: t("flows_chat_editing_on"),
      editingOff: t("flows_chat_editing_off"),
      askAfterPause: t("flows_chat_mode_ask_after_pause"),
      noAccess: t("flows_chat_no_access"),
      newConversationDescription: t("flows_chat_new_conversation_description")
    },
    lock:
      flow.published_version != null
        ? {
            reason: t("flows_chat_mode_edit_published"),
            intro: t("flows_chat_published_intro"),
            partnerDescription: t("flows_chat_partner_description_published")
          }
        : null,
    revision: () =>
      queryClient.getQueryData<FlowPublic>(flowKeys.flow(flow.id))?.draft_revision ?? 0,
    refusalText: (reason) =>
      reason === NO_MODEL ? t("flows_chat_no_model") : flowErrorText(reason, t),
    onRefused,
    references,
    // A run the chat starts shows in the answer, with its progress and
    // result; a change shows the steps it touched, each field before and after.
    toolCards: (call) => flowRunCardFor(call, flow, routeId, onAskChat) ?? flowChangeCardFor(call),
    headerActions:
      onAskChat && flow.steps.length > 0 ? <OptimizeFlowButton onAskChat={onAskChat} /> : null,
    onToolCallFinished: (call) => {
      if (isFlowsToolCall(call)) onFlowMayHaveChanged();
    },
    onAnswerFinished: onFlowMayHaveChanged
  };
}
