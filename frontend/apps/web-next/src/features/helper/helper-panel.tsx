import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import {
  DropdownMenu,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem
} from "@astryxdesign/core/DropdownMenu";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Heading, Text } from "@astryxdesign/core/Text";
import { hashKey, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, MessageSquare, Pencil, X } from "lucide-react";
import { useTranslations } from "use-intl";
import { useEffect, useMemo, useRef, useState } from "react";
import { LoadingState } from "@/components/composites/loading-state";
import { ListError } from "@/components/composites/query-state";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError, getErrorMessageForCode, unwrap } from "@/lib/api/errors";
import { mapSessionMessages } from "@/lib/chat/map-session";
import type { ChatPartner } from "@/lib/chat/types";
import { cn } from "@/lib/utils";
import { useSettingSwitch } from "@/features/admin/use-setting-switch";
import { ChatView, type ActivityState } from "@/features/chat/chat-view";
import { partnerCompletionModel } from "@/features/chat/partner-model";
import { useSpace } from "@/features/spaces/use-space";
import { useSpaceDisplayName } from "@/features/spaces/space-display-name";
import type { HelperAdapter, HelperChat } from "./helper-adapter";
import { HelperChatSettings, NewConversationButton } from "./helper-controls";

/**
 * The mode a message is sent in, picked beside the send button: Fråga (the
 * chat reads the target) or Redigera (its tools may change it). Where the
 * target has a revision, a change is fenced on the one on screen, so one
 * made while the target had changed is refused. Redigera after a pause may
 * start a new conversation: the panel then switches to it and says so. In
 * Redigera the button is in the warning colour and says so in words.
 */
function ModePicker({ chat, adapter }: { chat: HelperChat; adapter: HelperAdapter }) {
  const t = useTranslations();
  const announce = useAnnounce();
  const queryClient = useQueryClient();
  const { api, lock, revision, texts, onRefused } = adapter;
  // Whether the last saved switch started a new conversation.
  const restarted = useRef(false);
  const [savedEditing, setEditing] = useSettingSwitch(
    `helper-mode:${hashKey(api.key)}`,
    chat.editing,
    async (enabled) => {
      // A press queued behind a save that started a new conversation uses it.
      const current = queryClient.getQueryData<HelperChat>(api.key) ?? chat;
      const updated = await api.update(current.session_id, {
        editing: enabled,
        // The revision on screen when the switch was pressed, not one fetched later.
        ...(revision ? { expected_revision: revision() } : {})
      });
      restarted.current = updated.session_id !== current.session_id;
      // A read of the chat still on its way (after an answer, on the window's
      // focus) began before this change: it must not land after it.
      await queryClient.cancelQueries({ queryKey: api.key });
      queryClient.setQueryData(api.key, updated);
      return updated;
    },
    {
      onSaved: (enabled) => {
        announce(
          restarted.current
            ? t("flows_chat_new_conversation_after_pause")
            : enabled
              ? texts.editingOn
              : texts.editingOff
        );
      },
      onError: (error) => onRefused(error, t("flows_notice_mode_not_changed"))
    }
  );

  // A mode saved before the target was locked does not apply to it.
  const editing = savedEditing && !lock;
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
          description={texts.modeDescription.ask}
          icon={<MessageSquare aria-hidden="true" />}
        />
        <DropdownMenuRadioItem
          value="edit"
          label={t("flows_chat_mode_edit")}
          description={lock ? lock.reason : texts.modeDescription.edit}
          isDisabled={!!lock}
          icon={<Pencil aria-hidden="true" />}
        />
      </DropdownMenuRadioGroup>
    </DropdownMenu>
  );
}

/** The conversation itself, once the chat, its assistant and its history are loaded. */
function HelperConversation({ chat, adapter }: { chat: HelperChat; adapter: HelperAdapter }) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const { api, lock, texts, references } = adapter;
  // The composer leaves with the conversation: what the page puts into it
  // has nowhere to go until a composer reports itself again.
  const onComposer = references?.onComposer;
  useEffect(() => () => onComposer?.(null), [onComposer]);
  const { space } = useSpace();
  const spaceName = useSpaceDisplayName();
  const [activity, setActivity] = useState<ActivityState | null>(null);
  // The conversation shown first; a later one was started here ("Ny
  // konversation"), and its composer takes the focus the dialog left behind.
  const [firstSession] = useState(chat.session_id);

  const assistant = useQuery({
    queryKey: ["assistants", chat.assistant_id],
    queryFn: ({ signal }) =>
      unwrap(
        browserApi.GET("/api/v1/assistants/{id}/", {
          params: { path: { id: chat.assistant_id } },
          signal
        })
      )
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
  const editing = chat.editing && !lock;
  // The chat's assistant is hidden and named after its target; the panel
  // names it by what it does. A locked target cannot be changed (the
  // panel's header says why); in Fråga the chat changes nothing either.
  const partner: ChatPartner = {
    type: "assistant",
    id: model.id,
    name: texts.partnerName,
    description: lock
      ? lock.partnerDescription
      : editing
        ? texts.partnerDescription.edit
        : texts.partnerDescription.ask,
    allowedAttachments: model.allowed_attachments,
    insightEnabled: false,
    iconId: null,
    knowledge: [],
    spaceName,
    // The personal chat's lists ("Fortsätt", "Dina assistenter") are other
    // conversations, not this chat's: the helper never shows them.
    personalSpace: false,
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
      focusComposerIfLost={chat.session_id !== firstSession}
      partner={partner}
      initialSessionId={chat.session_id}
      initialMessages={initialMessages}
      activity={activity}
      onActivityChange={setActivity}
      startHeadingLevel={3}
      references={references}
      toolCards={adapter.toolCards}
      footerActions={
        <>
          {adapter.footerActions}
          <ModePicker chat={chat} adapter={adapter} />
        </>
      }
      placeholder={editing ? texts.placeholder.edit : texts.placeholder.ask}
      // Named by what a message does in the mode it is sent in.
      composerLabel={editing ? texts.composerLabelEdit : undefined}
      onToolCallFinished={adapter.onToolCallFinished}
      onAnswerFinished={() => {
        adapter.onAnswerFinished?.();
        // The turn's start may have left edit mode after a pause: show the mode the server holds.
        void queryClient.invalidateQueries({ queryKey: api.key });
      }}
    />
  );
}

/**
 * Says so when a read of the chat (after an answer, on the window's focus)
 * finds that the server left edit mode after a pause, politely and without
 * moving focus. The person's own changes are written into the cache, not
 * read, and announce themselves; a locked target shows Fråga either way.
 */
function useAnnounceModeFallback(chatHash: string, locked: boolean, text: string) {
  const announce = useAnnounce();
  const queryClient = useQueryClient();
  useEffect(() => {
    if (locked) return;
    const cache = queryClient.getQueryCache();
    let shown = cache.get<HelperChat>(chatHash)?.state.data;
    return cache.subscribe((event) => {
      if (event.type !== "updated" || event.query.queryHash !== chatHash) return;
      if (event.action.type !== "success") return;
      const read = event.action.data as HelperChat | undefined;
      const fellBack =
        !event.action.manual &&
        shown?.editing === true &&
        read?.editing === false &&
        read.session_id === shown.session_id;
      shown = read;
      if (fellBack) announce(text);
    });
  }, [announce, chatHash, locked, queryClient, text]);
}

type Unavailable = { status: "info" | "warning"; text: string };

/**
 * Why the chat cannot be opened: no edit access, no model with tools, or a
 * model whose limits nobody declared, which an administrator can put right.
 * Always in the catalog's words: the core's own message is English.
 */
function unavailableReason(
  error: unknown,
  adapter: HelperAdapter,
  t: ReturnType<typeof useTranslations>
): Unavailable | null {
  if (!(error instanceof EneoApiError)) return null;
  if (error.status === 403) return { status: "info", text: adapter.texts.noAccess };
  if (error.status !== 400) return null;
  if (error.reason === "unknown_model_capacity") {
    return { status: "warning", text: t("flows_chat_model_capacity_unknown") };
  }
  return {
    status: "info",
    text:
      adapter.refusalText?.(error.reason) ??
      getErrorMessageForCode(error.code, t) ??
      t("request_failed")
  };
}

/**
 * How a page that can put the panel away closes it: a close button at the
 * end of the title row, or, where the panel fills the screen, a way back at
 * its start.
 */
export type HelperPanelClose = {
  label: string;
  onClose: () => void;
  /** The panel fills the screen (a phone): the control is a way back, before the heading. */
  asBack?: boolean;
};

/**
 * A helper chat beside a page: an ordinary conversation with an assistant
 * whose tools reach only the page's target. It opens in Fråga; the picker
 * beside the send button lets the chat change the target, and the page
 * shows each change as the chat's tools make it. The adapter says what the
 * target is; everything else is the same on every page. A page that shows
 * the panel only on request passes `close`.
 */
export function HelperPanel({
  adapter,
  close
}: {
  adapter: HelperAdapter;
  close?: HelperPanelClose;
}) {
  const t = useTranslations();
  const { api, lock, texts } = adapter;
  const canUse = adapter.unavailable === null;
  // The person's chat for the target, created on first use. Reading it
  // again returns the same chat, but the server turns edit mode off when
  // the chat has been idle: it is read again when the window regains focus
  // (and after each answer), so a tab left open shows Fråga before the next
  // message is typed.
  const chat = useQuery<HelperChat>({
    queryKey: api.key,
    queryFn: () => api.open(),
    staleTime: Infinity,
    refetchOnWindowFocus: "always",
    retry: false,
    // Where the target says the chat is unavailable the core would refuse it
    // (a 403 still says so, should the page's reading be out of date).
    enabled: canUse
  });
  useAnnounceModeFallback(hashKey(api.key), !!lock, texts.askAfterPause);
  const unavailable: Unavailable | null =
    adapter.unavailable !== null
      ? { status: "info", text: adapter.unavailable }
      : chat.isError
        ? unavailableReason(chat.error, adapter, t)
        : null;
  const closeButton = close ? (
    <IconButton
      label={close.label}
      tooltip={close.label}
      variant="ghost"
      size="sm"
      icon={
        close.asBack ? (
          <ArrowLeft aria-hidden className="size-4" />
        ) : (
          <X aria-hidden className="size-4" />
        )
      }
      onClick={close.onClose}
    />
  ) : null;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-ax-border flex flex-col gap-0.5 border-b px-4 py-3">
        {/* The panel is narrow: the actions sit in the title row as icon
            buttons, and the chat's settings are behind one of them. */}
        <div className="flex items-center justify-between gap-2">
          {close?.asBack ? <span className="-my-1 -ms-2 shrink-0">{closeButton}</span> : null}
          <Heading
            level={2}
            weight="semibold"
            className={cn("min-w-0 truncate text-lg", close?.asBack && "flex-1")}
          >
            {texts.heading}
          </Heading>
          {chat.data || (close && !close.asBack) ? (
            <span className="-my-1 -me-2 flex shrink-0 items-center gap-0.5">
              {chat.data ? (
                <>
                  {adapter.headerActions}
                  <NewConversationButton
                    chat={chat.data}
                    api={api}
                    description={texts.newConversationDescription}
                    onRefused={adapter.onRefused}
                  />
                  <HelperChatSettings chat={chat.data} api={api} onRefused={adapter.onRefused} />
                </>
              ) : null}
              {close?.asBack ? null : closeButton}
            </span>
          ) : null}
        </div>
        {lock ? (
          <Text type="supporting" size="sm" as="p" display="block" className="m-0">
            {lock.intro}
          </Text>
        ) : null}
      </div>
      {chat.data ? (
        <HelperConversation chat={chat.data} adapter={adapter} />
      ) : canUse && !chat.isError ? (
        <LoadingState label={t("flows_chat_loading")} rows={3} className="p-4" />
      ) : (
        <div className="p-4">
          {unavailable ? (
            <Banner
              status={unavailable.status}
              title={t("flows_chat_unavailable")}
              description={unavailable.text}
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
