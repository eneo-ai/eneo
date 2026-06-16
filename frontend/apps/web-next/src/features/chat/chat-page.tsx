"use client";

import { useQuery } from "@tanstack/react-query";
import { History, Plus, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { mapSessionMessages } from "@/lib/chat/map-session";
import type { ChatPartner, EneoUIMessage } from "@/lib/chat/types";
import { cn } from "@/lib/utils";
import { ChatView } from "./chat-view";
import { HistoryPanel } from "./history-panel";

type ActiveConversation = {
  /** Remount key: changes when the conversation context changes. */
  key: string;
  sessionId: string | null;
  messages: EneoUIMessage[];
};

/**
 * Chat surface: ChatView with a collapsible history panel. History is closed by
 * default (avoids a second sidebar next to the space nav) and opens as an
 * inline panel on sm+ / an overlay drawer on mobile. Owns session selection; the
 * ChatView is remounted (key) per conversation so useChat state stays scoped.
 */
export function ChatPage({
  partner,
  initialSessionId,
  buildSessionUrl,
  modelSelector,
  actions
}: {
  partner: ChatPartner;
  initialSessionId?: string | null;
  /** Builds the shareable URL for a session id (kept in the address bar). */
  buildSessionUrl?: (sessionId: string | null) => string;
  /** Interactive model picker rendered in the composer (default-assistant). */
  modelSelector?: React.ReactNode;
  /** Header actions for editable partners (e.g. an Edit button for assistants). */
  actions?: React.ReactNode;
}) {
  const t = useTranslations();
  const [active, setActive] = useState<ActiveConversation | null>(
    initialSessionId ? null : { key: "new", sessionId: null, messages: [] }
  );
  const [pendingSessionId, setPendingSessionId] = useState<string | null>(initialSessionId ?? null);
  const [historyOpen, setHistoryOpen] = useState(false);

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
    // On mobile the panel is an overlay over the chat; close it so the picked
    // conversation is visible. On sm+ it sits inline, so keep it open to browse.
    if (window.matchMedia("(max-width: 639px)").matches) setHistoryOpen(false);
  }

  function newConversation() {
    setActive({ key: `new-${Date.now()}`, sessionId: null, messages: [] });
    updateUrl(null);
  }

  // Escape closes the panel (matches the overlay drawer's click-away on mobile).
  useEffect(() => {
    if (!historyOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setHistoryOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [historyOpen]);

  return (
    <div className="relative flex min-h-0 flex-1">
      <div className="flex min-h-0 min-w-0 flex-1 flex-col px-4">
        <div className="-mx-4 flex h-13 shrink-0 items-center gap-2.5 border-b px-4">
          <span className="truncate text-sm font-semibold">{partner.name}</span>
          <div className="ml-auto flex items-center gap-2">
            {/* Fixed-model partners show a read-only badge; the default
                assistant's interactive picker lives in the composer instead. */}
            {!modelSelector && partner.completionModel && (
              <Badge variant="outline" className="text-foreground font-medium">
                {partner.completionModel.name}
              </Badge>
            )}
            {actions}
            <Button variant="outline" size="sm" onClick={newConversation}>
              <Plus className="size-4" />
              <span className="hidden sm:inline">{t("new_conversation")}</span>
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className={cn("size-8", historyOpen && "bg-muted text-foreground")}
              aria-label={t("history")}
              aria-expanded={historyOpen}
              aria-controls="chat-history"
              onClick={() => setHistoryOpen((open) => !open)}
            >
              <History className="size-4" />
            </Button>
          </div>
        </div>
        {active ? (
          <ChatView
            key={active.key}
            partner={partner}
            initialSessionId={active.sessionId}
            initialMessages={active.messages}
            modelSelector={modelSelector}
            onNewConversation={newConversation}
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

      {historyOpen && (
        <>
          {/* Mobile: dim + click-away closes the overlay drawer. */}
          <button
            type="button"
            aria-hidden
            tabIndex={-1}
            onClick={() => setHistoryOpen(false)}
            className="bg-foreground/20 fixed inset-0 z-20 sm:hidden"
          />
          <aside
            id="chat-history"
            aria-label={t("history")}
            className="bg-sidebar text-sidebar-foreground border-sidebar-border fixed inset-y-0 right-0 z-30 flex w-72 max-w-[85vw] shrink-0 flex-col border-l p-3 sm:static sm:z-auto sm:max-w-none"
          >
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm font-semibold">{t("history")}</span>
              <Button
                variant="ghost"
                size="icon"
                className="size-7"
                aria-label={t("close")}
                onClick={() => setHistoryOpen(false)}
              >
                <X className="size-4" />
              </Button>
            </div>
            <HistoryPanel
              partner={partner}
              activeSessionId={active?.sessionId ?? pendingSessionId}
              onSelect={selectSession}
              onDeleted={(sessionId) => {
                if (active?.sessionId === sessionId) newConversation();
              }}
            />
          </aside>
        </>
      )}
    </div>
  );
}
