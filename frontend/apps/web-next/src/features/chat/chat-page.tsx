"use client";

import { Button } from "@astryxdesign/core/Button";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "@/lib/navigation";
import { useTranslations } from "next-intl";
import { useCallback, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { LoadingState } from "@/components/composites/loading-state";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { mapSessionMessages } from "@/lib/chat/map-session";
import { useElementWidth } from "@/lib/hooks/use-element-width";
import type { ChatPartner, EneoUIMessage } from "@/lib/chat/types";
import { ChatHeader, PartnerSwitcher, type HeaderMenuItem } from "./chat-header";
import { ChatView, type ActivityState } from "./chat-view";
import { setContextUsagePinned, useContextUsagePinned } from "./context-usage-bar";
import { HISTORY_WIDTH, HistoryAside } from "./history-panel";
import { InsightsPanel } from "./insights-panel";
import type { ChatPartnerSwitcherItem } from "./partner-switcher";
import { DeleteSessionDialog, RenameSessionDialog, useSessionMutations } from "./session-actions";
import { CONVERSATION_MIN_WIDTH, panelFitsBeside } from "./side-panel/side-panel";

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
  return Boolean(partner.insightEnabled && partner.type !== "default-assistant");
}

/**
 * How the history fits beside the conversation in a row of `width` px
 * (decision 14: the conversation keeps 480 px): not at all; only while no
 * side panel is open beside the conversation; or always (a panel fits next
 * to it too, or covers the conversation anyway). Where it does not fit, the
 * history is a sheet.
 */
function fitOfHistory(width: number): "none" | "alone" | "always" {
  const rest = width - HISTORY_WIDTH;
  if (rest < CONVERSATION_MIN_WIDTH) return "none";
  return panelFitsBeside(rest) || !panelFitsBeside(width) ? "always" : "alone";
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
  /** The space's assistants and group chats for the assistant selector. */
  switcherItems?: ChatPartnerSwitcherItem[];
  /** Editor link for partners the user may edit. */
  editHref?: string | null;
}) {
  const t = useTranslations();
  const router = useRouter();
  const [active, setActive] = useState<ActiveConversation | null>(() =>
    urlSessionId ? null : { key: "new", sessionId: null, messages: [], title: null, started: false }
  );
  const [pendingSessionId, setPendingSessionId] = useState<string | null>(urlSessionId);
  const [followedUrlSession, setFollowedUrlSession] = useState<string | null>(urlSessionId);
  const [historyOpen, setHistoryOpen] = useState(false);
  // The row that holds the conversation, its side panel and the history.
  const rowRef = useRef<HTMLDivElement>(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const [activity, setActivity] = useState<ActivityState | null>(null);
  const [renaming, setRenaming] = useState<{ id: string; name: string } | null>(null);
  const [deleting, setDeleting] = useState<{ id: string; name: string } | null>(null);
  const historyTrigger = useRef<HTMLElement | null>(null);

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
  const [tab, setTab] = useState<"chat" | "insights">(() =>
    typeof window !== "undefined" &&
    window.location.search.includes("tab=insights") &&
    partner.insightEnabled &&
    partner.type !== "default-assistant"
      ? "insights"
      : "chat"
  );

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

  function updateUrl(sessionId: string | null) {
    // Shallow history update on purpose: router.replace would start an RSC
    // navigation whose transition holds back streaming re-renders until the
    // server render resolves (the answer would then paint in one chunk).
    if (buildSessionUrl) window.history.replaceState(null, "", buildSessionUrl(sessionId));
  }

  const selectTab = useCallback((next: "chat" | "insights") => {
    setTab(next);
    setActivity(null);
    const url = new URL(window.location.href);
    if (next === "insights") url.searchParams.set("tab", "insights");
    else url.searchParams.delete("tab");
    window.history.replaceState(null, "", url);
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

  function selectSession(sessionId: string) {
    const showing = pendingSessionId ?? active?.sessionId ?? null;
    if (sessionId !== showing) {
      openSession(sessionId);
      updateUrl(sessionId);
    }
    // On phones the panel is an overlay over the chat; close it so the picked
    // conversation is visible. On wider screens it sits inline, so keep it open.
    if (!historyInline) closeHistory();
  }

  /** Starts a fresh conversation (`focusComposer`: it replaces a deleted one). */
  function startConversation(focusComposer: boolean) {
    setActive(newConversationState({ focusComposer }));
    setActivity(null);
    updateUrl(null);
  }
  const newConversation = () => startConversation(false);

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
  const effectiveTab = insightPartner ? tab : "chat";

  // Measured as how the history fits, so a resize re-renders the page only
  // when that changes. A panel open in the conversation behind Insikter
  // takes no room.
  const historyFit = useElementWidth(rowRef, fitOfHistory);
  const panelHere = panelOpen && effectiveTab === "chat";
  const historyInline = historyFit === "always" || (historyFit === "alone" && !panelHere);
  // The history beside the conversation would turn into a sheet only because
  // a panel is open beside it (the panel opened, or the window narrowed): it
  // gives way instead, in the same frame (ChatView reports the panel before
  // paint), rather than become a modal sheet over the panel. Opened next to
  // such a panel, it is a sheet; where it does not fit at all, it turns into
  // one.
  const historyBeside = historyOpen && historyInline;
  const [historyWasBeside, setHistoryWasBeside] = useState(historyBeside);
  const [gaveWay, setGaveWay] = useState(0);
  if (historyBeside !== historyWasBeside) {
    setHistoryWasBeside(historyBeside);
    if (historyWasBeside && historyOpen && historyFit === "alone" && panelHere) {
      setHistoryOpen(false);
      setGaveWay((count) => count + 1);
    }
  }
  // It had the focus (a view that opened by itself): the focus goes back to
  // what opened the history.
  useLayoutEffect(() => {
    if (gaveWay === 0 || document.activeElement !== document.body) return;
    const trigger = historyTrigger.current;
    historyTrigger.current = null;
    if (trigger?.isConnected) trigger.focus();
  }, [gaveWay]);
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
    ...(editHref
      ? [{ label: t("chat_edit_assistant"), onClick: () => router.push(editHref) }]
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
        title={effectiveTab === "insights" ? t("insights") : title}
        // The personal assistant picks its model in the composer.
        modelName={modelSelector ? null : (partner.completionModel?.name ?? null)}
        view={insightPartner ? { value: effectiveTab, onChange: selectTab } : null}
        historyOpen={historyOpen}
        onToggleHistory={toggleHistory}
        onNewConversation={newConversation}
        menuItems={menuItems}
        minimal={isPersonal && !started && pendingSessionId === null && effectiveTab === "chat"}
      />
      <div ref={rowRef} className="flex min-h-0 flex-1">
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          {insightPartner && effectiveTab === "insights" && (
            <InsightsPanel partner={insightPartner} />
          )}
          {/* The conversation stays mounted behind Insikter, so switching back
              keeps this visit's turns (and an answer still streaming). */}
          <div hidden={effectiveTab !== "chat"} className="flex min-h-0 min-w-0 flex-1 flex-col">
            {active ? (
              <ChatView
                key={active.key}
                partner={partner}
                initialSessionId={active.sessionId}
                initialMessages={active.messages}
                focusComposerIfLost={active.focusComposer}
                modelSelector={modelSelector}
                partnerToken={partnerToken}
                onNewConversation={newConversation}
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
                  updateUrl(id);
                }}
                activity={activity}
                onActivityChange={onActivityChange}
                onPanelOpenChange={setPanelOpen}
                layout={{
                  row: rowRef,
                  aside: historyBeside
                    ? { width: HISTORY_WIDTH, yields: historyFit === "alone" }
                    : null,
                  hidden: effectiveTab !== "chat"
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
            inline={historyInline}
            partner={partner}
            activeSessionId={sessionId ?? pendingSessionId}
            onSelect={selectSession}
            onDeleted={(id) => {
              if (active?.sessionId === id) newConversation();
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
