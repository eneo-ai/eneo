"use client";

import { Button } from "@astryxdesign/core/Button";
import { useMediaQuery } from "@astryxdesign/core/hooks";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useCallback, useRef, useState, type ReactNode } from "react";
import { LoadingState } from "@/components/composites/loading-state";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { mapSessionMessages } from "@/lib/chat/map-session";
import type { ChatPartner, EneoUIMessage } from "@/lib/chat/types";
import { ChatHeader, PartnerSwitcher, type HeaderMenuItem } from "./chat-header";
import { ChatView, type ActivityState } from "./chat-view";
import { HistoryAside } from "./history-panel";
import { InsightsPanel } from "./insights-panel";
import type { ChatPartnerSwitcherItem } from "./partner-switcher";
import { DeleteSessionDialog, RenameSessionDialog, useSessionMutations } from "./session-actions";

type ActiveConversation = {
  /** Remount key: changes when the conversation context changes. */
  key: string;
  sessionId: string | null;
  messages: EneoUIMessage[];
  title: string | null;
  feedback: 1 | -1 | null;
  /** The first question was sent (the header then shows a title). */
  started: boolean;
};

function hasInsights(partner: ChatPartner): partner is ChatPartner & {
  type: "assistant" | "group-chat";
} {
  return Boolean(partner.insightEnabled && partner.type !== "default-assistant");
}

let conversationCounter = 0;

/** A fresh, unsent conversation (a new remount key each time). */
function newConversationState(): ActiveConversation {
  conversationCounter += 1;
  return {
    key: `new-${conversationCounter}`,
    sessionId: null,
    messages: [],
    title: null,
    feedback: null,
    started: false
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
    feedback: session.feedback?.value ?? null,
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
  // History is an inline panel from 768px up, an overlay drawer below.
  const historyInline = useMediaQuery("(min-width: 768px)");
  const [active, setActive] = useState<ActiveConversation | null>(() =>
    urlSessionId
      ? null
      : { key: "new", sessionId: null, messages: [], title: null, feedback: null, started: false }
  );
  const [pendingSessionId, setPendingSessionId] = useState<string | null>(urlSessionId);
  const [followedUrlSession, setFollowedUrlSession] = useState<string | null>(urlSessionId);
  const [historyOpen, setHistoryOpen] = useState(false);
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

  function newConversation() {
    setActive(newConversationState());
    setActivity(null);
    updateUrl(null);
  }

  const onActivityChange = useCallback((next: ActivityState | null) => {
    if (next) setHistoryOpen(false);
    setActivity(next);
  }, []);

  /** A conversation was rated (answer thumbs or the history menu). */
  function rated(id: string, value: 1 | -1) {
    setActive((current) => (current?.sessionId === id ? { ...current, feedback: value } : current));
  }

  const { rename, remove } = useSessionMutations(partner, {
    onRenamed: (id, name) => {
      setRenaming(null);
      setActive((current) => (current?.sessionId === id ? { ...current, title: name } : current));
    },
    onDeleted: (id) => {
      setDeleting(null);
      if (active?.sessionId === id) newConversation();
    }
  });

  const insightPartner = hasInsights(partner) ? partner : null;
  const effectiveTab = insightPartner ? tab : "chat";
  const sessionId = active?.sessionId ?? null;
  const started = Boolean(active?.started);
  // The conversation title is the page's h1; the start state's greeting is h1 instead.
  const title = active && started ? (active.title ?? t("new_conversation")) : null;
  const isPersonal = partner.type === "default-assistant";

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
        modelName={partner.completionModel?.name ?? null}
        view={insightPartner ? { value: effectiveTab, onChange: selectTab } : null}
        historyOpen={historyOpen}
        onToggleHistory={toggleHistory}
        onNewConversation={newConversation}
        menuItems={menuItems}
        minimal={isPersonal && !started && pendingSessionId === null && effectiveTab === "chat"}
      />
      <div className="flex min-h-0 flex-1">
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
                feedback={active.feedback}
                onRated={rated}
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
              />
            ) : detail.isError ? (
              <div className="flex flex-col items-center gap-3 p-6 text-center">
                <p className="text-ax-error text-sm">{t("chat_conversation_load_failed")}</p>
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
            onRated={rated}
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
