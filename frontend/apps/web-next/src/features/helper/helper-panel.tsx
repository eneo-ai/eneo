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
import { hashKey, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { ArrowLeft, MessageSquare, Pencil, X } from "lucide-react";
import { useTranslations } from "use-intl";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { LoadingState } from "@/components/composites/loading-state";
import { ListError } from "@/components/composites/query-state";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError, getErrorMessageForCode, unwrap } from "@/lib/api/errors";
import { mapSessionMessages } from "@/lib/chat/map-session";
import type { ChatPartner } from "@/lib/chat/types";
import { useFocusRescue } from "@/lib/focus-rescue";
import { cn } from "@/lib/utils";
import { settingSwitchScope, useSettingSwitch } from "@/features/admin/use-setting-switch";
import type { ChatReferences, ComposerInsert } from "@/features/chat/chat-references";
import { ChatView, type ActivityState } from "@/features/chat/chat-view";
import { composerField } from "@/features/chat/conversation-layout";
import { partnerCompletionModel } from "@/features/chat/partner-model";
import type { SidePanelLayout } from "@/features/chat/side-panel/side-panel";
import { useSpace } from "@/features/spaces/use-space";
import { useSpaceDisplayName } from "@/features/spaces/space-display-name";
import { EarlierConversation } from "./earlier-conversation";
import type {
  HelperAdapter,
  HelperChat,
  HelperChatApi,
  HelperConversation,
  HelperModes
} from "./helper-adapter";
import {
  ConversationHistoryMenu,
  HelperChatSettings,
  NewConversationButton,
  useConversationTime
} from "./helper-controls";

/**
 * The helper is a narrow column beside the page it helps with: an answer's
 * activity, a file or the overview that has no room beside the conversation
 * covers the conversation in that column, not the whole window.
 */
const HELPER_PANEL_LAYOUT: SidePanelLayout = { inColumn: true };

/** The mode switch of one chat: its saves run one after another in its own queue. */
const modeSwitchId = (api: HelperChatApi) => `helper-mode:${hashKey(api.key)}`;

/**
 * Resolves once the chat's mode saves in flight now have settled: true when
 * each was saved. The picker shows a new mode at once and saves it
 * meanwhile, so a message sent before the save lands waits for it and runs
 * in the mode on screen; a save that failed holds the message.
 */
function modeSaved(queryClient: QueryClient, api: HelperChatApi): Promise<boolean> {
  const scope = settingSwitchScope(modeSwitchId(api)).id;
  const cache = queryClient.getMutationCache();
  const saves = cache.findAll({
    status: "pending",
    predicate: (mutation) => mutation.options.scope?.id === scope
  });
  if (saves.length === 0) return Promise.resolve(true);
  return new Promise((resolve) => {
    const unsubscribe = cache.subscribe(() => {
      if (saves.some((save) => save.state.status === "pending")) return;
      unsubscribe();
      resolve(saves.every((save) => save.state.status === "success"));
    });
  });
}

/**
 * The mode a message is sent in, picked beside the send button: Fråga (the
 * chat reads the target) or Redigera (its tools may change it). Where the
 * target has a revision, a change is fenced on the one on screen, so one
 * made while the target had changed is refused. Redigera after a pause may
 * start a new conversation: the panel then switches to it and says so. In
 * Redigera the button is in the warning colour and says so in words.
 */
function ModePicker({
  chat,
  adapter,
  modes
}: {
  chat: HelperChat;
  adapter: HelperAdapter;
  modes: HelperModes;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const queryClient = useQueryClient();
  const { api, lock, revision, onRefused } = adapter;
  // Whether the last saved switch started a new conversation.
  const restarted = useRef(false);
  const [savedEditing, setEditing] = useSettingSwitch(
    modeSwitchId(api),
    chat.editing === true,
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
              ? modes.editingOn
              : modes.editingOff
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
          description={modes.description.ask}
          icon={<MessageSquare aria-hidden="true" />}
        />
        <DropdownMenuRadioItem
          value="edit"
          label={t("flows_chat_mode_edit")}
          description={lock ? lock.reason : modes.description.edit}
          isDisabled={!!lock}
          icon={<Pencil aria-hidden="true" />}
        />
      </DropdownMenuRadioGroup>
    </DropdownMenu>
  );
}

/**
 * What the page is told of the conversation's composer: the composer while
 * the conversation is on screen. While an earlier conversation is read in
 * its place, a stand-in: what the page puts in (a prepared question, a
 * card's request) brings the conversation back and goes into its composer
 * once it shows. The composer leaves with the conversation: what the page
 * puts into it then has nowhere to go until a composer reports itself again.
 * Returns the references the conversation itself is given.
 */
function useComposerOnScreen(
  references: ChatReferences | undefined,
  shown: boolean,
  onShowCurrent: () => void
): ChatReferences | undefined {
  const onComposer = references?.onComposer;
  const [composer, setComposer] = useState<ComposerInsert | null>(null);
  // What the page put in while the conversation was away, in order.
  const waiting = useRef<((input: ComposerInsert) => void)[]>([]);
  const standIn = useMemo<ComposerInsert | null>(
    () =>
      composer && {
        insertText: (text) => {
          waiting.current.push((input) => input.insertText(text));
          onShowCurrent();
        },
        insertToken: (token) => {
          waiting.current.push((input) => input.insertToken(token));
          onShowCurrent();
        }
      },
    [composer, onShowCurrent]
  );
  const reported = shown ? composer : standIn;
  useEffect(() => {
    if (reported !== null) onComposer?.(reported);
  }, [onComposer, reported]);
  useEffect(() => () => onComposer?.(null), [onComposer]);
  useEffect(() => {
    if (!shown || composer === null) return;
    for (const put of waiting.current.splice(0)) put(composer);
  }, [shown, composer]);
  return useMemo(
    () => (references ? { ...references, onComposer: setComposer } : undefined),
    [references]
  );
}

/** The conversation itself, once the chat, its assistant and its history are loaded. */
function HelperConversation({
  chat,
  adapter,
  shown,
  onShowCurrent
}: {
  chat: HelperChat;
  adapter: HelperAdapter;
  /** False while an earlier conversation is read in this one's place. */
  shown: boolean;
  /** Brings this conversation back in place of an earlier one. */
  onShowCurrent: () => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const { api, lock, texts, modes } = adapter;
  const references = useComposerOnScreen(adapter.references, shown, onShowCurrent);
  const { space } = useSpace();
  const spaceName = useSpaceDisplayName();
  const [activity, setActivity] = useState<ActivityState | null>(null);
  // The conversation shown first; a later one was started here ("Ny
  // konversation"), and its composer takes the focus the dialog left behind.
  const [firstSession] = useState(chat.session_id);
  // Only a target with modes is ever in Redigera.
  const editing = modes !== null && chat.editing === true && !lock;
  // Why the page held the last message back: what `beforeSend` said, until
  // the next message goes, or the page's standing reason, while it stands.
  const [held, setHeld] = useState<{ reason: string; standing: boolean } | null>(null);
  const beforeSend = adapter.beforeSend;
  const sendHold = adapter.sendHold ?? null;
  // Saved or dropped: the notice goes with its reason, and only a held
  // message brings it back.
  if (held?.standing && sendHold === null) setHeld(null);
  // A message goes once its files are uploaded, with the callbacks of the
  // render it was sent from: the standing reason is read from here then.
  const sendHoldNow = useRef(sendHold);
  useEffect(() => {
    sendHoldNow.current = sendHold;
  }, [sendHold]);
  // A target with modes asks first too: a message waits for a mode save in flight.
  const asksFirst = modes !== null || beforeSend !== undefined || adapter.sendHold !== undefined;
  // Where the standing reason can be settled, as the page offers it now.
  const heldAction = held?.standing ? (adapter.sendHoldAction ?? null) : null;

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
  // The chat's assistant is hidden and named after its target; the panel
  // names it by what it does. A locked target cannot be changed (the
  // panel's header says why); in Fråga the chat changes nothing either.
  const partner: ChatPartner = {
    type: "assistant",
    id: model.id,
    name: texts.partnerName,
    description: lock
      ? lock.partnerDescription
      : editing && modes
        ? modes.edit.partnerDescription
        : texts.partnerDescription,
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
    <>
      {held !== null ? (
        // Something that just happened: read out at once, and kept until a
        // message goes or its standing reason has gone.
        <div className="shrink-0 px-4 pt-3">
          <Banner
            role="alert"
            status="error"
            title={t("helper_send_held")}
            description={held.reason}
            endContent={
              heldAction ? (
                <Button label={heldAction.label} size="sm" onClick={heldAction.onAction} />
              ) : undefined
            }
          />
        </div>
      ) : null}
      <ChatView
        key={chat.session_id}
        focusComposerIfLost={chat.session_id !== firstSession}
        partner={partner}
        initialSessionId={chat.session_id}
        initialMessages={initialMessages}
        activity={activity}
        onActivityChange={setActivity}
        layout={HELPER_PANEL_LAYOUT}
        startHeadingLevel={3}
        references={references}
        toolCards={adapter.toolCards}
        footerActions={
          <>
            {adapter.footerActions}
            {modes ? <ModePicker chat={chat} adapter={adapter} modes={modes} /> : null}
          </>
        }
        placeholder={editing && modes ? modes.edit.placeholder : texts.placeholder}
        // Named by what a message does in the mode it is sent in.
        composerLabel={editing && modes ? modes.edit.composerLabel : undefined}
        onToolCallFinished={adapter.onToolCallFinished}
        onAnswerFinished={() => {
          adapter.onAnswerFinished?.();
          // The turn's start may have left edit mode after a pause: show the mode the server holds.
          void queryClient.invalidateQueries({ queryKey: api.key });
        }}
        beforeSend={
          asksFirst
            ? async () => {
                const standing = sendHoldNow.current;
                if (standing !== null) {
                  setHeld({ reason: standing, standing: true });
                  return false;
                }
                // A mode save that failed holds the message; the picker shows its refusal.
                if (modes && !(await modeSaved(queryClient, api))) {
                  setHeld(null);
                  return false;
                }
                const reason = beforeSend ? await beforeSend() : null;
                setHeld(reason === null ? null : { reason, standing: false });
                return reason === null;
              }
            : undefined
        }
      />
    </>
  );
}

/**
 * A target that starts each visit afresh (`freshPerVisit`): what the panel
 * read of the chat is forgotten when the panel goes with its page, so the
 * next visit shows no conversation before its own fresh one.
 */
function useForgetChatAfterVisit(chatHash: string, fresh: boolean) {
  const queryClient = useQueryClient();
  useEffect(() => {
    if (!fresh) return;
    return () => {
      const cache = queryClient.getQueryCache();
      const read = cache.get(chatHash);
      if (read) cache.remove(read);
    };
  }, [chatHash, fresh, queryClient]);
}

/**
 * Says `text` when a read of the chat (after an answer, on the window's
 * focus) finds that the server left edit mode after a pause, politely and
 * without moving focus. The person's own changes are written into the
 * cache, not read, and announce themselves. Null says nothing: a locked
 * target shows Fråga either way, and a target without modes has no mode to
 * leave.
 */
function useAnnounceModeFallback(chatHash: string, text: string | null) {
  const announce = useAnnounce();
  const queryClient = useQueryClient();
  useEffect(() => {
    if (text === null) return;
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
  }, [announce, chatHash, queryClient, text]);
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
 * whose tools reach only the page's target. On a target with modes it opens
 * in Fråga; the picker beside the send button lets the chat change the
 * target, and the page shows each change as the chat's tools make it. A
 * target without modes has no picker: its chat proposes each change for the
 * person to apply. The adapter says what the target is; everything else is
 * the same on every page. A page that shows the panel only on request
 * passes `close`, and `open` while it keeps the panel mounted when it is
 * put away.
 *
 * Where the target lists its conversations, "Tidigare konversationer" in
 * the title row shows an earlier one in the current one's place, read
 * only. The current conversation stays as it was meanwhile (an answer on its
 * way goes on); going back, starting a new conversation, or putting the
 * panel away and opening it again shows it once more.
 */
export function HelperPanel({
  adapter,
  close,
  open = true
}: {
  adapter: HelperAdapter;
  close?: HelperPanelClose;
  /** False while the page has put the panel away and keeps it mounted. */
  open?: boolean;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const rescue = useFocusRescue();
  const timeOf = useConversationTime();
  const queryClient = useQueryClient();
  const { api, lock, modes, texts } = adapter;
  const canUse = adapter.unavailable === null;
  const chatHash = hashKey(api.key);
  const freshPerVisit = api.freshPerVisit === true;
  // The person's chat for the target, created on first use. Reading it
  // again returns the same chat, but the server turns edit mode off when
  // the chat has been idle: it is read again when the window regains focus
  // (and after each answer), so a tab left open shows Fråga before the next
  // message is typed. A target that starts each visit afresh asks for that
  // on the visit's first read only: a later read finds the chat read.
  const chat = useQuery<HelperChat>({
    queryKey: api.key,
    queryFn: () =>
      api.open({
        fresh: freshPerVisit && queryClient.getQueryData(api.key) === undefined
      }),
    staleTime: Infinity,
    refetchOnWindowFocus: "always",
    retry: false,
    // Where the target says the chat is unavailable the core would refuse it
    // (a 403 still says so, should the page's reading be out of date).
    enabled: canUse
  });
  useForgetChatAfterVisit(chatHash, freshPerVisit);
  useAnnounceModeFallback(chatHash, lock || !modes ? null : modes.askAfterPause);

  // The earlier conversation read in the current one's place, with the
  // current conversation it was picked from: another current conversation
  // (one started here) shows instead, as does putting the panel away.
  const [earlier, setEarlier] = useState<{
    conversation: HelperConversation;
    from: string;
  } | null>(null);
  if (!open && earlier !== null) setEarlier(null);
  const shownEarlier =
    earlier !== null && earlier.from === chat.data?.session_id ? earlier.conversation : null;
  const showCurrent = useCallback(() => setEarlier(null), []);
  const current = useRef<HTMLDivElement>(null);
  const pickEarlier = (conversation: HelperConversation) => {
    if (!chat.data) return;
    setEarlier({ conversation, from: chat.data.session_id });
    announce(t("helper_earlier_shown", { time: timeOf(conversation.last_asked_at) }));
  };
  // Back in the current conversation, its composer takes the focus the bar had.
  const backToCurrent = () => {
    showCurrent();
    rescue(() => composerField(current.current));
  };
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
                  {api.listConversations ? (
                    <ConversationHistoryMenu
                      chat={chat.data}
                      api={api}
                      list={api.listConversations}
                      onPick={pickEarlier}
                    />
                  ) : null}
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
        <>
          {shownEarlier ? (
            <EarlierConversation
              key={shownEarlier.session_id}
              chat={chat.data}
              conversation={shownEarlier}
              adapter={adapter}
              onBack={backToCurrent}
            />
          ) : null}
          {/* Kept while an earlier conversation is read, so an answer on its
              way and what is typed in the composer stay. */}
          <div
            ref={current}
            hidden={shownEarlier !== null}
            className="flex min-h-0 flex-1 flex-col"
          >
            <HelperConversation
              chat={chat.data}
              adapter={adapter}
              shown={shownEarlier === null}
              onShowCurrent={showCurrent}
            />
          </div>
        </>
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
