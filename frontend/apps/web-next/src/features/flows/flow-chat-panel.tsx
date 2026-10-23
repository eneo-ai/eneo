"use client";

import { Badge } from "@astryxdesign/core/Badge";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Heading, Text } from "@astryxdesign/core/Text";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useMemo, useRef, useState } from "react";
import { QuietBanner } from "@/components/astryx/banner";
import { Switch } from "@/components/astryx/switch";
import { LoadingState } from "@/components/composites/loading-state";
import { ListError } from "@/components/composites/query-state";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError, unwrap } from "@/lib/api/errors";
import { mapSessionMessages } from "@/lib/chat/map-session";
import type { ChatPartner } from "@/lib/chat/types";
import { useSettingSwitch } from "@/features/admin/use-setting-switch";
import { retryPartnerQuery } from "@/features/chat/chat-partner-state";
import { ChatView, type ActivityState, type ComposerOffer } from "@/features/chat/chat-view";
import { partnerCompletionModel } from "@/features/chat/partner-model";
import type { ToolCallRecord } from "@/features/chat/side-panel/message-tool-calls";
import { useSpace } from "@/features/spaces/use-space";
import { useSpaceDisplayName } from "@/features/spaces/frame/space-header";
import {
  FlowChatModelPickers,
  NewConversationButton,
  OptimizeFlowButton
} from "./flow-chat-controls";
import {
  authoringChatQueryOptions,
  flowKeys,
  setAuthoringMode,
  type FlowAuthoringChat,
  type FlowPublic
} from "./flows-api";

/** The loopback server the flow chat's tools run on (the backend's `FLOWS_SERVER_NAME`). */
export const FLOWS_SERVER_NAME = "flows";

/** A call on Eneo's own flows server; an external server an admin named "flows" does not count. */
export function isFlowsToolCall(call: Pick<ToolCallRecord, "serverName" | "isInternal">): boolean {
  return call.serverName === FLOWS_SERVER_NAME && call.isInternal !== false;
}

type ChatPanelProps = {
  flow: FlowPublic;
  /** A tool of the chat finished, or an answer ended: the flow may have changed. */
  onFlowMayHaveChanged: () => void;
  /** A refused mode change, shown with the page's other refusals. */
  onRefused: (error: unknown, title: string) => void;
  /** A message the page prepared for the composer ("Fråga assistenten"); never sent by itself. */
  offer: ComposerOffer | null;
  /** The composer took `offer`. */
  onOfferTaken: () => void;
  /** Prepares a message for the composer (the page shows the chat first, on a phone). */
  onAskChat: (text: string) => void;
};

/**
 * The switch between reading and editing. In edit mode the chat's tools may
 * change the draft; it is fenced on the revision on screen, so a switch made
 * while the flow had changed is refused and the page reloads the flow.
 * Turning it on after a pause may start a new conversation: the panel then
 * switches to it and says so.
 */
function EditModeSwitch({
  chat,
  onRefused
}: {
  chat: FlowAuthoringChat;
  onRefused: ChatPanelProps["onRefused"];
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const queryClient = useQueryClient();
  const chatKey = flowKeys.authoringChat(chat.flow_id);
  // Whether the last saved switch started a new conversation.
  const restarted = useRef(false);
  const [editing, setEditing] = useSettingSwitch(
    `flow-authoring-mode:${chat.flow_id}`,
    chat.editing,
    async (enabled) => {
      // A press queued behind a save that started a new conversation uses it.
      const current = queryClient.getQueryData<FlowAuthoringChat>(chatKey) ?? chat;
      const updated = await setAuthoringMode(current, {
        editing: enabled,
        // The revision on screen when the switch was pressed, not one fetched later.
        expectedRevision:
          queryClient.getQueryData<FlowPublic>(flowKeys.flow(chat.flow_id))?.draft_revision ?? 0
      });
      restarted.current = updated.session_id !== current.session_id;
      queryClient.setQueryData(chatKey, updated);
      return updated;
    },
    {
      onSaved: (enabled) => {
        announce(
          restarted.current
            ? t("flows_chat_new_conversation_after_pause")
            : enabled
              ? t("flows_chat_editing_on")
              : t("flows_chat_editing_off")
        );
      },
      onError: (error) => onRefused(error, t("flows_notice_mode_not_changed"))
    }
  );

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
      <Switch
        label={t("flows_chat_editing")}
        description={t("flows_chat_editing_hint")}
        value={editing}
        onChange={setEditing}
      />
      <Badge
        variant={editing ? "warning" : "neutral"}
        label={editing ? t("flows_chat_can_edit") : t("flows_chat_reads_only")}
      />
    </div>
  );
}

/** The conversation itself, once the chat, its assistant and its history are loaded. */
function AuthoringConversation({
  chat,
  onFlowMayHaveChanged,
  offer,
  onOfferTaken
}: Pick<ChatPanelProps, "onFlowMayHaveChanged" | "offer" | "onOfferTaken"> & {
  chat: FlowAuthoringChat;
}) {
  const t = useTranslations();
  const { space } = useSpace();
  const spaceName = useSpaceDisplayName();
  const [activity, setActivity] = useState<ActivityState | null>(null);

  const assistant = useQuery({
    queryKey: ["assistants", chat.assistant_id],
    queryFn: ({ signal }) =>
      unwrap(
        browserApi.GET("/api/v1/assistants/{id}/", {
          params: { path: { id: chat.assistant_id } },
          signal
        })
      ),
    retry: retryPartnerQuery
  });
  // Read once per visit: the view owns the messages from then on.
  const conversation = useQuery({
    queryKey: ["conversations", "detail", chat.session_id],
    queryFn: ({ signal }) =>
      unwrap(
        browserApi.GET("/api/v1/conversations/{session_id}/", {
          params: { path: { session_id: chat.session_id } },
          signal
        })
      ),
    staleTime: Infinity,
    gcTime: 0,
    refetchOnWindowFocus: false,
    retry: false
  });
  const initialMessages = useMemo(
    () => (conversation.data ? mapSessionMessages(conversation.data.messages) : []),
    [conversation.data]
  );

  const failed = [assistant, conversation].find((query) => query.isError);
  if (failed) {
    return (
      <div className="p-4">
        <ListError error={failed.error} onRetry={() => void failed.refetch()} />
      </div>
    );
  }
  if (!assistant.data || !conversation.data) {
    return <LoadingState label={t("flows_chat_loading")} rows={3} className="p-4" />;
  }

  const model = assistant.data;
  // The chat's assistant is hidden and named after the flow; the panel names
  // it by what it does.
  const partner: ChatPartner = {
    type: "assistant",
    id: model.id,
    name: t("flows_chat_partner_name"),
    description: t("flows_chat_partner_description"),
    allowedAttachments: model.allowed_attachments,
    insightEnabled: false,
    iconId: null,
    knowledge: [],
    spaceName,
    personalSpace: space.personal,
    securityClassification: space.security_classification?.name ?? null,
    mcpServers: model.mcp_servers ?? [],
    enabledCapabilities: model.enabled_capabilities,
    availableCapabilities: model.available_capabilities,
    effectiveConfig: model.effective_config ?? null,
    completionModel: partnerCompletionModel(model, space.completion_models)
  };

  return (
    <ChatView
      key={chat.session_id}
      partner={partner}
      initialSessionId={chat.session_id}
      initialMessages={initialMessages}
      activity={activity}
      onActivityChange={setActivity}
      startHeadingLevel={3}
      onToolCallFinished={(call) => {
        if (isFlowsToolCall(call)) onFlowMayHaveChanged();
      }}
      onAnswerFinished={onFlowMayHaveChanged}
      offer={offer}
      onOfferTaken={onOfferTaken}
    />
  );
}

/** Why the chat cannot be opened, as the core said it: no edit access, or no model with tools. */
function unavailableMessage(error: unknown, t: ReturnType<typeof useTranslations>): string | null {
  if (!(error instanceof EneoApiError)) return null;
  if (error.status === 403) return t("flows_chat_no_access");
  if (error.status === 400) return t("flows_chat_no_model");
  return null;
}

/**
 * The flow's chat: an ordinary conversation with an assistant whose tools
 * reach only this flow. It opens in view mode; the switch above it lets the
 * chat change the draft, and the page shows each change as the chat's tools
 * make it.
 */
export function FlowChatPanel({
  flow,
  onFlowMayHaveChanged,
  onRefused,
  offer,
  onOfferTaken,
  onAskChat
}: ChatPanelProps) {
  const t = useTranslations();
  // The chat needs edit access; without it the core would refuse it (a 403
  // still says so, should the flag be out of date).
  const mayEdit = flow.permissions.can_edit;
  const chat = useQuery({ ...authoringChatQueryOptions(flow.id), enabled: mayEdit });
  const unavailable = !mayEdit
    ? t("flows_chat_no_access")
    : chat.isError
      ? unavailableMessage(chat.error, t)
      : null;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-ax-border flex flex-col gap-3 border-b px-4 py-3">
        <div className="flex flex-col gap-0.5">
          <Heading level={2} weight="semibold" className="text-lg">
            {t("flows_chat_heading")}
          </Heading>
          <Text type="supporting" size="sm" as="p" display="block" className="m-0">
            {t("flows_chat_intro")}
          </Text>
        </div>
        {chat.data ? (
          <>
            <EditModeSwitch chat={chat.data} onRefused={onRefused} />
            <div className="flex flex-wrap items-center justify-between gap-2">
              <FlowChatModelPickers chat={chat.data} onRefused={onRefused} />
              <span className="flex flex-wrap items-center gap-1">
                <OptimizeFlowButton onAskChat={onAskChat} />
                <NewConversationButton chat={chat.data} onRefused={onRefused} />
              </span>
            </div>
          </>
        ) : null}
      </div>
      {chat.data ? (
        <AuthoringConversation
          chat={chat.data}
          onFlowMayHaveChanged={onFlowMayHaveChanged}
          offer={offer}
          onOfferTaken={onOfferTaken}
        />
      ) : mayEdit && !chat.isError ? (
        <LoadingState label={t("flows_chat_loading")} rows={3} className="p-4" />
      ) : (
        <div className="p-4">
          {unavailable ? (
            <QuietBanner
              status="info"
              title={t("flows_chat_unavailable")}
              description={unavailable}
              collapsible={false}
            />
          ) : (
            <ListError
              error={chat.error}
              title={t("flows_chat_failed")}
              onRetry={() => void chat.refetch()}
            />
          )}
        </div>
      )}
    </div>
  );
}
