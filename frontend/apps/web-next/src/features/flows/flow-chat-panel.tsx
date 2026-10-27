"use client";

import { Button } from "@astryxdesign/core/Button";
import {
  DropdownMenu,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem
} from "@astryxdesign/core/DropdownMenu";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Heading, Text } from "@astryxdesign/core/Text";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageSquare, Pencil } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useMemo, useRef, useState } from "react";
import { Banner } from "@astryxdesign/core/Banner";
import { LoadingState } from "@/components/composites/loading-state";
import { ListError } from "@/components/composites/query-state";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError, unwrap } from "@/lib/api/errors";
import { mapSessionMessages } from "@/lib/chat/map-session";
import type { ChatPartner } from "@/lib/chat/types";
import { cn } from "@/lib/utils";
import { useSettingSwitch } from "@/features/admin/use-setting-switch";
import { retryPartnerQuery } from "@/features/chat/chat-partner-state";
import { ChatView, type ActivityState } from "@/features/chat/chat-view";
import { partnerCompletionModel } from "@/features/chat/partner-model";
import { useSpace } from "@/features/spaces/use-space";
import { useSpaceDisplayName } from "@/features/spaces/frame/space-header";
import type { ComposerInsert } from "@/features/chat/chat-references";
import { flowRunCardFor } from "./chat/flow-run-card";
import { isFlowsToolCall } from "./chat/flows-tool-call";
import { useFlowChatReferences } from "./chat/use-flow-chat-references";
import { FlowChatSettings, NewConversationButton, OptimizeFlowButton } from "./flow-chat-controls";
import {
  authoringChatQueryOptions,
  flowKeys,
  setAuthoringMode,
  type FlowAuthoringChat,
  type FlowPublic
} from "./flows-api";

type ChatPanelProps = {
  flow: FlowPublic;
  /** A tool of the chat finished, or an answer ended: the flow may have changed. */
  onFlowMayHaveChanged: () => void;
  /** A refused mode change, shown with the page's other refusals. */
  onRefused: (error: unknown, title: string) => void;
  /**
   * The chat's composer while it is on screen, or null: the page's
   * FlowReferences (the one reference card of the page, for the chat and
   * the definition alike) and "Fråga assistenten" put things into it.
   */
  onComposer: (composer: ComposerInsert | null) => void;
  /**
   * Puts a prepared request ("Optimera flödet") into the composer at the
   * caret, never sending it nor changing the mode; absent until the
   * composer is on the page.
   */
  onAskChat?: (text: string) => void;
};

/**
 * The mode a message is sent in, picked beside the send button: Fråga
 * (the chat reads the flow) or Redigera (its tools may change the draft).
 * A change is fenced on the revision on screen, so one made while the flow
 * had changed is refused and the page reloads the flow. Redigera after a
 * pause may start a new conversation: the panel then switches to it and
 * says so. In Redigera the button is in the warning colour and says so in
 * words.
 */
function ModePicker({
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

  const label = editing ? t("flows_chat_mode_edit") : t("flows_chat_mode_ask");
  return (
    <DropdownMenu
      placement="above"
      renderTrigger={(props) => (
        <Button
          {...props}
          variant="ghost"
          size="sm"
          label={label}
          // "Läge: Redigera": a state, not an action, to a screen reader.
          aria-label={t("flows_chat_mode_current", { mode: label })}
          icon={
            editing ? (
              <Pencil aria-hidden="true" className="size-4" />
            ) : (
              <MessageSquare aria-hidden="true" className="size-4" />
            )
          }
          className={cn(
            "rounded-ax-element h-8 px-2 text-[13px] font-semibold pointer-coarse:h-11",
            editing ? "text-ax-warning" : "text-ax-text-secondary hover:text-ax-text"
          )}
        />
      )}
    >
      <DropdownMenuRadioGroup
        label={t("flows_chat_mode")}
        value={editing ? "edit" : "ask"}
        onChange={(value) => setEditing(value === "edit")}
      >
        <DropdownMenuRadioItem
          value="ask"
          label={t("flows_chat_mode_ask")}
          description={t("flows_chat_mode_ask_description")}
          icon={<MessageSquare aria-hidden="true" />}
        />
        <DropdownMenuRadioItem
          value="edit"
          label={t("flows_chat_mode_edit")}
          description={t("flows_chat_mode_edit_description")}
          icon={<Pencil aria-hidden="true" />}
        />
      </DropdownMenuRadioGroup>
    </DropdownMenu>
  );
}

/** The conversation itself, once the chat, its assistant and its history are loaded. */
function AuthoringConversation({
  flow,
  chat,
  onFlowMayHaveChanged,
  onRefused,
  onComposer
}: Pick<ChatPanelProps, "onComposer"> & {
  flow: FlowPublic;
  chat: FlowAuthoringChat;
  onFlowMayHaveChanged: () => void;
  onRefused: ChatPanelProps["onRefused"];
}) {
  const t = useTranslations();
  const { references, composer } = useFlowChatReferences(flow);
  // The page's references (pills, the card, "Fråga assistenten") reach the composer through it.
  useEffect(() => {
    onComposer(composer);
  }, [composer, onComposer]);
  useEffect(() => () => onComposer(null), [onComposer]);
  const { space, routeId } = useSpace();
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
      references={references}
      // A run the chat starts shows in the answer, with its progress and result.
      toolCards={(call) => flowRunCardFor(call, flow, routeId)}
      footerActions={<ModePicker chat={chat} onRefused={onRefused} />}
      placeholder={
        chat.editing ? t("flows_chat_placeholder_edit") : t("flows_chat_placeholder_ask")
      }
      onToolCallFinished={(call) => {
        if (isFlowsToolCall(call)) onFlowMayHaveChanged();
      }}
      onAnswerFinished={onFlowMayHaveChanged}
    />
  );
}

/** Why the chat cannot be opened, as the core said it: no edit access, or no model with tools. */
function unavailableMessage(error: unknown, t: ReturnType<typeof useTranslations>): string | null {
  if (!(error instanceof EneoApiError)) return null;
  if (error.status === 403) return t("flows_chat_no_access");
  if (error.status === 400) {
    // The core names the refusal; only a missing model has a text of its own.
    return error.reason === "flow_authoring_chat_no_model" || !error.message
      ? t("flows_chat_no_model")
      : error.message;
  }
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
  onComposer,
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
      <div className="border-ax-border flex flex-col gap-0.5 border-b px-4 py-3">
        {/* The panel is narrow: the actions sit in the title row as icon
            buttons, and the chat's settings are behind one of them. */}
        <div className="flex items-center justify-between gap-2">
          <Heading level={2} weight="semibold" className="min-w-0 truncate text-lg">
            {t("flows_chat_heading")}
          </Heading>
          {chat.data ? (
            <span className="-my-1 -me-2 flex shrink-0 items-center gap-0.5">
              {onAskChat ? <OptimizeFlowButton onAskChat={onAskChat} /> : null}
              <NewConversationButton chat={chat.data} onRefused={onRefused} />
              <FlowChatSettings chat={chat.data} onRefused={onRefused} />
            </span>
          ) : null}
        </div>
        <Text type="supporting" size="sm" as="p" display="block" className="m-0">
          {t("flows_chat_intro")}
        </Text>
      </div>
      {chat.data ? (
        <AuthoringConversation
          flow={flow}
          chat={chat.data}
          onFlowMayHaveChanged={onFlowMayHaveChanged}
          onRefused={onRefused}
          onComposer={onComposer}
        />
      ) : mayEdit && !chat.isError ? (
        <LoadingState label={t("flows_chat_loading")} rows={3} className="p-4" />
      ) : (
        <div className="p-4">
          {unavailable ? (
            <Banner
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
