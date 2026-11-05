import { Button } from "@astryxdesign/core/Button";
import { useQuery } from "@tanstack/react-query";
import { replaceUrl, useSearchParams, type UrlOptions } from "@/lib/navigation";
import { useTranslations } from "use-intl";
import { useCallback, useRef, useState, type ReactNode } from "react";
import { LoadingState } from "@/components/composites/loading-state";
import type { LeaveConfirmationHandle } from "@/components/composites/leave-confirmation";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { mapSessionMessages } from "@/lib/chat/map-session";
import type { ChatPartner, EneoUIMessage } from "@/lib/chat/types";
import { ChatHeader, PartnerSwitcher, type HeaderMenuItem } from "./chat-header";
import { ChatView, type ActivityState, type ChatDebugHandle } from "./chat-view";
import { setContextUsagePinned, useContextUsagePinned } from "./context-usage-bar";
import { HistoryAside, HistoryTab } from "./history-panel";
import { InsightsPanel } from "./insights-panel";
import type { ChatPartnerSwitcherItem } from "./partner-switcher";
import { DeleteSessionDialog, RenameSessionDialog, useSessionMutations } from "./session-actions";
import { CHAT_PANEL_IDS, readChatTab, type ChatTab } from "./chat-url";
import { useAppContext } from "@/components/providers/app-context";
import { useFocusRescue } from "@/lib/focus-rescue";
import { usePhoneScreen } from "@/lib/hooks/use-media-match";

type ActiveConversation = {
  /** Remount key: changes when the conversation context changes. */
  key: string;
  sessionId: string | null;
  messages: EneoUIMessage[];
  title: string | null;
  /** The first question was sent (the header then shows a title). */
  started: boolean;
  /** Replaces a deleted conversation: its composer takes focus if focus was lost. */
  focusComposer?: boolean;
};

function hasInsights(partner: ChatPartner): partner is ChatPartner & {
  type: "assistant" | "group-chat";
} {
  return Boolean(
    partner.insightEnabled &&
    partner.permissions?.includes("insight_view") &&
    partner.type !== "default-assistant"
  );
}

let conversationCounter = 0;

/** A fresh, unsent conversation (a new remount key each time). */
function newConversationState({ focusComposer = false } = {}): ActiveConversation {
  conversationCounter += 1;
  return {
    key: `new-${conversationCounter}`,
    sessionId: null,
    messages: [],
    title: null,
    started: false,
    focusComposer
  };
}

/** A saved conversation as loaded from the backend. */
function savedConversationState(session: Schema<"SessionPublic">): ActiveConversation {
  return {
    key: session.id,
    sessionId: session.id,
    messages: mapSessionMessages(session.messages),
    // An untitled session has an empty name: the header then says "Ny konversation".
    title: session.name || null,
    started: session.messages.length > 0
  };
}

/**
 * Chat surface: header, the conversation (ChatView, remounted per
 * conversation so useChat state stays scoped) or the insights view, and one
 * right-hand panel at a time (history or an answer's activity). Owns session
 * selection and keeps `?session_id=` (or the route's session segment) in the
 * address bar. Opening another conversation replaces the current view at once
 * (a loading state until it arrives), so nothing typed or streamed there can
 * land in the wrong conversation.
 */
export function ChatPage({
  partner,
  sessionId: urlSessionId = null,
  buildSessionUrl,
  modelSelector,
  skills,
  switcherItems,
  editHref
}: {
  partner: ChatPartner;
  /**
   * The conversation in the URL (`?session_id=` or the route segment). Followed
   * when it changes on the same route: a different id opens that conversation,
   * none starts a new one. URL updates made by this page itself are ignored.
   */
  sessionId?: string | null;
  /** Builds the shareable URL for a session id (kept in the address bar). */
  buildSessionUrl?: (sessionId: string | null) => string;
  /** Interactive model picker rendered in the composer (default-assistant). */
  modelSelector?: ReactNode;
  /** The personal chat's Skills control, beside Verktyg in the composer. */
  skills?: ReactNode;
  /** The space's assistants and group chats for the assistant selector. */
  switcherItems?: ChatPartnerSwitcherItem[];
  /** Editor link for partners the user may edit. */
  editHref?: string | null;
}) {
  const t = useTranslations();
  const leaveConfirmation = useRef<LeaveConfirmationHandle>(null);
  const [active, setActive] = useState<ActiveConversation | null>(() =>
    urlSessionId ? null : { key: "new", sessionId: null, messages: [], title: null, started: false }
  );
  const [pendingSessionId, setPendingSessionId] = useState<string | null>(urlSessionId);
  const [followedUrlSession, setFollowedUrlSession] = useState<string | null>(urlSessionId);
  const [historyOpen, setHistoryOpen] = useState(false);
  // Reported by the conversation, which knows when an answer is saved.
  const [debugReady, setDebugReady] = useState(false);
  // The row that holds the conversation, its side panel and the history.
  const rowRef = useRef<HTMLDivElement>(null);
  const [activity, setActivity] = useState<ActivityState | null>(null);
  const [renaming, setRenaming] = useState<{ id: string; name: string } | null>(null);
  const [deleting, setDeleting] = useState<{ id: string; name: string } | null>(null);
  const historyTrigger = useRef<HTMLElement | null>(null);
  const rescueFocus = useFocusRescue();
  const debugRef = useRef<ChatDebugHandle>(null);
  const { can } = useAppContext();
  const debugAvailable = can("assistant_debug") && partner.type !== "group-chat";

  /** Opens a saved conversation: the current view goes until it has loaded. */
  function openSession(sessionId: string) {
    setPendingSessionId(sessionId);
    setActive(null);
    setActivity(null);
  }

  // Follow the URL (SideNav "Senaste", "Ny konversation", back/forward) on the
  // same route. The page writes its own URL with replaceState too; those
  // changes already match what it shows, so they are no-ops here.
  if (urlSessionId !== followedUrlSession) {
    setFollowedUrlSession(urlSessionId);
    const showing = pendingSessionId ?? active?.sessionId ?? null;
    if (urlSessionId !== showing) {
      if (urlSessionId) {
        openSession(urlSessionId);
      } else {
        setPendingSessionId(null);
        setActive(newConversationState());
        setActivity(null);
      }
    }
  }
  const searchParams = useSearchParams();
  const tab = readChatTab(searchParams);

  // Loading a session (initial deep-link or history click) goes through
  // pendingSessionId; the mapped messages then become the active conversation.
  // Never served from cache: re-opening a conversation must show its latest
  // messages. Switching again cancels the earlier request (its signal).
  const detail = useQuery({
    queryKey: ["conversations", "detail", pendingSessionId],
    enabled: pendingSessionId !== null,
    staleTime: 0,
    gcTime: 0,
    // A missing or forbidden session will not appear on retry; fail once, visibly.
    retry: false,
    queryFn: ({ signal }) =>
      unwrap(
        browserApi.GET("/api/v1/conversations/{session_id}/", {
          params: { path: { session_id: pendingSessionId! } },
          signal
        })
      )
  });
  // The result belongs to the session still asked for (the query key), so an
  // earlier, slower response can never replace a later pick.
  if (pendingSessionId !== null && detail.isSuccess) {
    setPendingSessionId(null);
    setActive(savedConversationState(detail.data));
  }

  /** The conversation's URL; the view stays unless `nextTab` changes it (a late session id keeps it). */
  function updateUrl(sessionId: string | null, options?: UrlOptions, nextTab: ChatTab = viewTab) {
    // The navigation seam commits same-route updates without waiting for
    // background session refreshes, so streaming stays responsive.
    if (buildSessionUrl) {
      const url = new URL(buildSessionUrl(sessionId), window.location.href);
      if (nextTab === "chat") url.searchParams.delete("tab");
      else url.searchParams.set("tab", nextTab);
      replaceUrl(url, options);
    }
  }

  const selectTab = useCallback((next: ChatTab) => {
    setActivity(null);
    const url = new URL(window.location.href);
    if (next === "chat") url.searchParams.delete("tab");
    else url.searchParams.set("tab", next);
    // Not a departure: the conversation stays mounted with its draft, so the leave guard stays out.
    replaceUrl(url, { ignoreBlocker: true });
  }, []);

  const closeHistory = useCallback(() => {
    setHistoryOpen(false);
    const trigger = historyTrigger.current;
    historyTrigger.current = null;
    if (trigger?.isConnected) requestAnimationFrame(() => trigger.focus());
  }, []);

  function toggleHistory() {
    if (historyOpen) {
      closeHistory();
      return;
    }
    historyTrigger.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setActivity(null);
    setHistoryOpen(true);
  }

  /** Historik's rows go with the tab, the picked one too: focus moves to the conversation's panel. */
  function moveFocusToChat() {
    if (viewTab === "history") rescueFocus(() => document.getElementById(CHAT_PANEL_IDS.chat));
  }

  /**
   * Historik can also go without a pick: a window narrowed to the phone layout, which has no
   * tabs. A ref's cleanup runs before the panel leaves the page, so it can still see the focus.
   */
  const historyContents = useCallback(
    (contents: HTMLDivElement) => () => {
      if (contents.contains(document.activeElement)) {
        rescueFocus(() => document.getElementById(CHAT_PANEL_IDS.chat));
      }
    },
    [rescueFocus]
  );

  function selectSession(sessionId: string) {
    const showing = pendingSessionId ?? active?.sessionId ?? null;
    if (sessionId !== showing) {
      // Picked from Historik, it opens in Chatt, as in Svelte.
      confirmConversationChange(() => {
        moveFocusToChat();
        openSession(sessionId);
        updateUrl(sessionId, { ignoreBlocker: true }, "chat");
        closeHistory();
      });
      return;
    }
    moveFocusToChat();
    if (viewTab === "history") selectTab("chat");
    // The phone's history sheet covers the chat: it closes so the conversation shows.
    closeHistory();
  }

  /**
   * Starts a fresh conversation (`focusComposer`: it replaces a deleted one).
   * The view stays: deleting from Historik keeps Historik open, as in Svelte.
   */
  function startConversation(focusComposer: boolean, nextTab: ChatTab = viewTab) {
    setActive(newConversationState({ focusComposer }));
    setActivity(null);
    updateUrl(null, { ignoreBlocker: true }, nextTab);
  }
  function confirmConversationChange(action: () => void) {
    // The current view owns both document edits and unsent attachments. Keep
    // it mounted until it accepts a reset, including resets at the same URL.
    if (leaveConfirmation.current) leaveConfirmation.current.confirm(action);
    else action();
  }
  // Ny konversation opens Chatt, from any view.
  const newConversation = () => confirmConversationChange(() => startConversation(false, "chat"));

  const onActivityChange = useCallback((next: ActivityState | null) => {
    if (next) setHistoryOpen(false);
    setActivity(next);
  }, []);

  const { rename, remove } = useSessionMutations(partner, {
    onRenamed: (id, name) => {
      setRenaming(null);
      setActive((current) => (current?.sessionId === id ? { ...current, title: name } : current));
    },
    onDeleted: (id) => {
      setDeleting(null);
      // The header menu that opened the dialog can go with the conversation's
      // actions, so the fresh conversation takes focus if it was lost.
      if (active?.sessionId === id) startConversation(true);
    }
  });

  const insightPartner = hasInsights(partner) ? partner : null;
  // A phone has no tabs: Historik is its sheet, Insikter a menu row.
  const phone = usePhoneScreen();
  const viewTab: ChatTab =
    tab === "insights"
      ? insightPartner
        ? "insights"
        : "chat"
      : tab === "history" && !phone
        ? "history"
        : "chat";

  const sessionId = active?.sessionId ?? null;
  const started = Boolean(active?.started);
  // The page has one h1: the conversation title in the header, the start
  // state's greeting (no title here), the loading label while a conversation
  // loads, or the error that it could not be loaded (rendered below).
  const title = active
    ? started
      ? (active.title ?? t("new_conversation"))
      : null
    : detail.isError
      ? null
      : t("chat_loading_conversation");
  const isPersonal = partner.type === "default-assistant";
  // The context meter under the composer shows itself only when the window
  // is filling up; this pins it for people who want to watch it.
  const contextUsagePinned = useContextUsagePinned();

  const menuItems: HeaderMenuItem[] = [
    ...(sessionId
      ? [
          {
            label: t("chat_rename_conversation"),
            onClick: () => setRenaming({ id: sessionId, name: active?.title ?? "" })
          }
        ]
      : []),
    {
      label: contextUsagePinned ? t("context_usage_menu_hide") : t("context_usage_menu_show"),
      onClick: () => setContextUsagePinned(!contextUsagePinned)
    },
    ...(sessionId
      ? [
          {
            label: t("chat_delete_conversation"),
            variant: "destructive" as const,
            onClick: () => setDeleting({ id: sessionId, name: active?.title ?? "" })
          }
        ]
      : [])
  ];

  const partnerToken =
    isPersonal && (switcherItems?.length ?? 0) > 1 ? (
      <PartnerSwitcher partner={partner} items={switcherItems} subtitle={null} variant="token" />
    ) : undefined;

  return (
    <div className="bg-ax-surface relative flex min-h-0 flex-1 flex-col">
      <ChatHeader
        partner={partner}
        switcherItems={switcherItems}
        // Historik and Insikter are the page's h1 themselves; the conversation's title names Chatt.
        title={viewTab === "chat" ? title : t(viewTab)}
        // The personal assistant picks its model in the composer.
        modelName={modelSelector ? null : (partner.completionModel?.name ?? null)}
        view={{ value: viewTab, onChange: selectTab, hasInsights: insightPartner !== null }}
        editHref={editHref}
        debug={
          debugAvailable
            ? {
                isEnabled: debugReady,
                onOpen: (trigger) => {
                  // Felsökning shows in Chatt, beside the answer it explains.
                  if (viewTab !== "chat") selectTab("chat");
                  debugRef.current?.openDebug(trigger);
                }
              }
            : null
        }
        historyOpen={historyOpen}
        onToggleHistory={toggleHistory}
        onNewConversation={newConversation}
        minimal={isPersonal && !started && pendingSessionId === null && viewTab === "chat"}
        menuItems={menuItems}
      />
      <div ref={rowRef} className="flex min-h-0 flex-1">
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          {/* The tabs' panels are always there for aria-controls; only the
              selected one renders its content (Historik loads on demand). */}
          {insightPartner && (
            <div
              id={CHAT_PANEL_IDS.insights}
              role={phone ? undefined : "tabpanel"}
              aria-label={t("insights")}
              hidden={viewTab !== "insights"}
              className="flex min-h-0 min-w-0 flex-1 flex-col"
            >
              {viewTab === "insights" && <InsightsPanel partner={insightPartner} />}
            </div>
          )}
          <div
            id={CHAT_PANEL_IDS.history}
            role={phone ? undefined : "tabpanel"}
            aria-label={t("history")}
            hidden={viewTab !== "history"}
            className="flex min-h-0 min-w-0 flex-1 flex-col p-6"
          >
            {viewTab === "history" && (
              <div ref={historyContents} className="contents">
                <HistoryTab
                  partner={partner}
                  activeSessionId={sessionId ?? pendingSessionId}
                  onSelect={selectSession}
                  onDeleted={(id) => {
                    if (active?.sessionId === id) startConversation(false);
                  }}
                  onRenamed={(id, name) =>
                    setActive((current) =>
                      current?.sessionId === id ? { ...current, title: name } : current
                    )
                  }
                />
              </div>
            )}
          </div>
          {/* The conversation stays mounted behind Insikter, so switching back
              keeps this visit's turns (and an answer still streaming). */}
          <div
            id={CHAT_PANEL_IDS.chat}
            role={phone ? undefined : "tabpanel"}
            aria-label={t("chat")}
            hidden={viewTab !== "chat"}
            tabIndex={-1}
            className="focus-visible:outline-ring flex min-h-0 min-w-0 flex-1 flex-col focus-visible:outline-2 focus-visible:-outline-offset-2"
          >
            {active ? (
              <ChatView
                key={active.key}
                leaveConfirmationRef={leaveConfirmation}
                debugRef={debugRef}
                onDebugReadyChange={setDebugReady}
                partner={partner}
                initialSessionId={active.sessionId}
                initialMessages={active.messages}
                focusComposerIfLost={active.focusComposer}
                modelSelector={modelSelector}
                skills={skills}
                partnerToken={partnerToken}
                // Its controls (the context meter, the model dialog) go with
                // the view, so the fresh composer takes focus if it was lost.
                onNewConversation={(prepare) =>
                  confirmConversationChange(() => {
                    prepare?.();
                    startConversation(true);
                  })
                }
                onStartedChange={(value) =>
                  setActive((current) =>
                    current && current.started !== value ? { ...current, started: value } : current
                  )
                }
                onTitle={(name) =>
                  setActive((current) => (current ? { ...current, title: name } : current))
                }
                onSessionCreated={(id) => {
                  setActive((current) => (current ? { ...current, sessionId: id } : current));
                  updateUrl(id, { ignoreBlocker: true });
                }}
                activity={activity}
                onActivityChange={onActivityChange}
                layout={{
                  row: rowRef,
                  hidden: viewTab !== "chat"
                }}
              />
            ) : detail.isError ? (
              <div className="flex flex-col items-center gap-3 p-6 text-center">
                <h1 className="text-ax-error text-sm">{t("chat_conversation_load_failed")}</h1>
                <Button
                  label={t("new_conversation")}
                  variant="secondary"
                  onClick={newConversation}
                />
              </div>
            ) : (
              <div className="mx-auto w-full max-w-[712px] p-6">
                <LoadingState rows={4} label={t("chat_loading_conversation")} />
              </div>
            )}
          </div>
        </div>
        {historyOpen && (
          <HistoryAside
            partner={partner}
            activeSessionId={sessionId ?? pendingSessionId}
            onSelect={selectSession}
            onDeleted={(id) => {
              if (active?.sessionId === id) startConversation(false);
            }}
            onRenamed={(id, name) =>
              setActive((current) =>
                current?.sessionId === id ? { ...current, title: name } : current
              )
            }
            onClose={closeHistory}
          />
        )}
      </div>

      <RenameSessionDialog
        session={renaming}
        pending={rename.isPending}
        onCancel={() => setRenaming(null)}
        onSave={(name) => renaming && rename.mutate({ id: renaming.id, name })}
      />
      <DeleteSessionDialog
        session={deleting}
        pending={remove.isPending}
        onCancel={() => setDeleting(null)}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
    </div>
  );
}
