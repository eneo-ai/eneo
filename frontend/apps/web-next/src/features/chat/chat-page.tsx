"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { mapSessionMessages } from "@/lib/chat/map-session";
import type { ChatPartner, EneoUIMessage } from "@/lib/chat/types";
import { ChatView } from "./chat-view";
import { HistoryPanel } from "./history-panel";

type ActiveConversation = {
  /** Remount key: changes when the conversation context changes. */
  key: string;
  sessionId: string | null;
  messages: EneoUIMessage[];
};

/**
 * Chat surface: history sidebar + ChatView. Owns session selection; the
 * ChatView is remounted (key) per conversation so useChat state stays scoped.
 */
export function ChatPage({
  partner,
  initialSessionId,
  buildSessionUrl,
  headerExtra
}: {
  partner: ChatPartner;
  initialSessionId?: string | null;
  /** Builds the shareable URL for a session id (kept in the address bar). */
  buildSessionUrl?: (sessionId: string | null) => string;
  headerExtra?: React.ReactNode;
}) {
  const [active, setActive] = useState<ActiveConversation | null>(
    initialSessionId ? null : { key: "new", sessionId: null, messages: [] }
  );
  const [pendingSessionId, setPendingSessionId] = useState<string | null>(initialSessionId ?? null);

  // Loading a session (initial deep-link or history click) goes through
  // pendingSessionId; the mapped messages then become the active conversation.
  useQuery({
    queryKey: ["conversations", "detail", pendingSessionId],
    enabled: pendingSessionId !== null,
    queryFn: async () => {
      const session = await unwrap(
        browserApi.GET("/api/v1/conversations/{session_id}/", {
          params: { path: { session_id: pendingSessionId! } }
        })
      );
      setActive({
        key: session.id,
        sessionId: session.id,
        messages: mapSessionMessages(session.messages)
      });
      setPendingSessionId(null);
      return session;
    }
  });

  function updateUrl(sessionId: string | null) {
    // Shallow history update on purpose: router.replace would start an RSC
    // navigation whose transition holds back streaming re-renders until the
    // server render resolves (the answer would then paint in one chunk).
    if (buildSessionUrl) window.history.replaceState(null, "", buildSessionUrl(sessionId));
  }

  function selectSession(sessionId: string) {
    setPendingSessionId(sessionId);
    updateUrl(sessionId);
  }

  function newConversation() {
    setActive({ key: `new-${Date.now()}`, sessionId: null, messages: [] });
    updateUrl(null);
  }

  return (
    <div className="flex min-h-0 flex-1">
      <aside className="bg-sidebar text-sidebar-foreground border-sidebar-border hidden w-64 shrink-0 flex-col border-r p-3 lg:flex">
        <HistoryPanel
          partner={partner}
          activeSessionId={active?.sessionId ?? pendingSessionId}
          onSelect={selectSession}
          onNew={newConversation}
          onDeleted={(sessionId) => {
            if (active?.sessionId === sessionId) newConversation();
          }}
        />
      </aside>
      <div className="flex min-h-0 min-w-0 flex-1 flex-col px-4">
        <div className="-mx-4 flex h-13 shrink-0 items-center gap-2.5 border-b px-4">
          <span className="truncate text-sm font-semibold">{partner.name}</span>
          <div className="ml-auto flex items-center gap-2">
            {headerExtra ??
              (partner.completionModel && (
                <Badge variant="outline" className="text-foreground font-medium">
                  {partner.completionModel.name}
                </Badge>
              ))}
          </div>
        </div>
        {active ? (
          <ChatView
            key={active.key}
            partner={partner}
            initialSessionId={active.sessionId}
            initialMessages={active.messages}
            onSessionCreated={(sessionId) => {
              setActive((current) => current && { ...current, sessionId });
              updateUrl(sessionId);
            }}
          />
        ) : (
          <div className="flex flex-1 flex-col gap-3 p-6">
            <Skeleton className="h-16 w-2/3" />
            <Skeleton className="h-16 w-1/2 self-end" />
          </div>
        )}
      </div>
    </div>
  );
}
