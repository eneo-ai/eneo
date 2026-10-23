"use client";

import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useId, useRef, useState } from "react";
import { TextInput } from "@/components/astryx/text-input";
import { ClientTime } from "@/components/composites/client-time";
import { EmptyState } from "@/components/composites/empty-state";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { cursorPagination, flattenPages } from "@/lib/api/pagination";
import { mapSessionMessages } from "@/lib/chat/map-session";
import { displayPartnerName } from "@/lib/chat/partner-name";
import type { ChatPartner } from "@/lib/chat/types";
import { cn } from "@/lib/utils";
import { ChatMessage } from "@/features/chat/chat-message";
import { insightPartnerQuery, insightRangeParams, type InsightRange } from "./insights-range";

const PAGE_SIZE = 50;
const SEARCH_DEBOUNCE_MS = 250;

type Partner = ChatPartner & { type: "assistant" | "group-chat" };

function SessionList({
  partner,
  range,
  selectedId,
  onSelect
}: {
  partner: Partner;
  range: InsightRange;
  selectedId: string | null;
  onSelect: (sessionId: string) => void;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const headingId = useId();
  const listRef = useRef<HTMLUListElement>(null);
  const [searchInput, setSearchInput] = useState("");
  const [filter, setFilter] = useState("");
  const params = insightRangeParams(range);
  const query = insightPartnerQuery(partner);

  // The name filter is sent once typing pauses.
  const debounce = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => {
    clearTimeout(debounce.current);
    debounce.current = setTimeout(() => setFilter(searchInput.trim()), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(debounce.current);
  }, [searchInput]);

  const sessions = useInfiniteQuery({
    ...cursorPagination,
    queryKey: [
      "conversation-insights",
      "sessions",
      partner.type,
      partner.id,
      params.fromDate,
      params.toDate,
      filter
    ],
    queryFn: ({ pageParam, signal }) =>
      unwrap(
        browserApi.GET("/api/v1/analysis/conversation-insights/sessions/", {
          params: {
            query: {
              ...query,
              limit: PAGE_SIZE,
              cursor: pageParam,
              name_filter: filter || undefined,
              start_date: params.fromDate,
              end_date: params.toDate
            }
          },
          signal
        })
      )
  });
  const pages = sessions.data?.pages;
  const rows = flattenPages(pages);
  const total = pages?.at(-1)?.total_count ?? rows.length;

  // "Ladda fler": once the page it asked for renders, say how far the list
  // reaches and focus that page's first conversation (the button itself goes
  // away with the last page).
  const focusPage = useRef<number | null>(null);
  const pageCount = pages?.length ?? 0;
  useEffect(() => {
    const page = focusPage.current;
    if (page === null || pageCount <= page) return;
    focusPage.current = null;
    announce(
      sessions.hasNextPage
        ? t("loaded_conversations_count", { loaded: rows.length, total })
        : t("loaded_all_conversations", { total })
    );
    const first = pages?.[page]?.items[0];
    if (!first) return;
    listRef.current
      ?.querySelector<HTMLElement>(`[data-session-row="${CSS.escape(first.id)}"]`)
      ?.focus();
  }, [pageCount, pages, announce, t, rows.length, total, sessions.hasNextPage]);

  function loadMore() {
    if (sessions.isFetchingNextPage) return;
    focusPage.current = pageCount;
    void sessions.fetchNextPage();
  }

  return (
    <section aria-labelledby={headingId} className="flex min-h-0 flex-col gap-3">
      <h3 id={headingId} className="text-sm font-semibold">
        {t("insights_sessions_heading")}
      </h3>
      <TextInput
        label={t("chat_history_search")}
        isLabelHidden
        placeholder={t("chat_history_search")}
        value={searchInput}
        onChange={setSearchInput}
        startIcon={Search}
        hasClear
        size="sm"
        width="100%"
      />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <QueryStateBoundary query={sessions} rows={5}>
          {() =>
            rows.length === 0 ? (
              <EmptyState title={t("insights_no_conversations")} isCompact framed={false} />
            ) : (
              <>
                <ul ref={listRef} className="flex flex-col gap-0.5">
                  {rows.map((session) => {
                    const selected = session.id === selectedId;
                    return (
                      <li key={session.id}>
                        <button
                          type="button"
                          data-session-row={session.id}
                          aria-pressed={selected}
                          onClick={() => onSelect(session.id)}
                          className={cn(
                            "focus-visible:outline-ring rounded-ax-element flex min-h-9 w-full min-w-0 flex-col items-start gap-0.5 px-2.5 py-1.5 text-start text-[13px] focus-visible:outline-2 focus-visible:-outline-offset-2 pointer-coarse:min-h-11",
                            selected ? "bg-ax-selected font-semibold" : "hover:bg-ax-hover"
                          )}
                        >
                          <span className="w-full truncate">
                            {session.name || t("chat_history_untitled")}
                          </span>
                          {session.created_at && (
                            <span className="text-ax-text-secondary text-xs font-normal tabular-nums">
                              <ClientTime value={session.created_at} format="date_time" />
                            </span>
                          )}
                        </button>
                      </li>
                    );
                  })}
                </ul>
                <div className="text-ax-text-secondary flex flex-col items-center gap-2 py-3 text-xs">
                  {sessions.hasNextPage ? (
                    <>
                      <Button
                        variant="secondary"
                        size="sm"
                        label={t("load_more_conversations")}
                        isLoading={sessions.isFetchingNextPage}
                        isInterruptible
                        onClick={loadMore}
                      />
                      <span>{t("loaded_conversations_count", { loaded: rows.length, total })}</span>
                    </>
                  ) : (
                    <span>{t("loaded_all_conversations", { total })}</span>
                  )}
                </div>
              </>
            )
          }
        </QueryStateBoundary>
      </div>
    </section>
  );
}

function SessionPreview({ partner, sessionId }: { partner: Partner; sessionId: string | null }) {
  const t = useTranslations();
  const headingId = useId();
  const session = useQuery({
    queryKey: ["conversation-insights", "session", sessionId],
    enabled: sessionId !== null,
    queryFn: ({ signal }) =>
      unwrap(
        browserApi.GET("/api/v1/analysis/conversation-insights/sessions/{session_id}/", {
          params: { path: { session_id: sessionId! } },
          signal
        })
      )
  });
  const assistant = {
    id: partner.id,
    name: displayPartnerName(partner, t),
    iconId: partner.iconId
  };

  return (
    <section
      aria-labelledby={headingId}
      className="bg-ax-sunken border-ax-border rounded-ax-container flex min-h-0 flex-col gap-3 border p-3"
    >
      <h3 id={headingId} className="text-sm font-semibold">
        {t("insights_preview_label")}
      </h3>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {sessionId === null ? (
          <p className="text-ax-text-secondary text-sm">{t("insights_select_conversation")}</p>
        ) : (
          <QueryStateBoundary query={session} rows={3} variant="text">
            {(data) => {
              const messages = mapSessionMessages(data.messages);
              return messages.length === 0 ? (
                <p className="text-ax-text-secondary text-sm">
                  {t("insights_conversation_no_messages")}
                </p>
              ) : (
                <div className="flex flex-col gap-5">
                  {messages.map((message) => (
                    <ChatMessage key={message.id} message={message} assistant={assistant} />
                  ))}
                </div>
              );
            }}
          </QueryStateBoundary>
        )}
      </div>
    </section>
  );
}

/**
 * "Utforska konversationer": every conversation users had with the partner
 * in the chosen period (owners and editors of a partner with insights on),
 * searchable by title and loaded a page at a time, with the picked one
 * readable beside the list.
 */
export function ExploreConversationsDialog({
  partner,
  range,
  isOpen,
  onOpenChange
}: {
  partner: Partner;
  range: InsightRange;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  return (
    <Dialog isOpen={isOpen} onOpenChange={onOpenChange} width={960} maxHeight="85dvh">
      <DialogHeader
        title={t("explore_conversations")}
        subtitle={t("view_all_conversations_users_had")}
        onOpenChange={onOpenChange}
      />
      <div className="grid min-h-0 gap-4 lg:h-[60dvh] lg:grid-cols-2">
        <SessionList
          partner={partner}
          range={range}
          selectedId={selectedId}
          onSelect={setSelectedId}
        />
        <SessionPreview partner={partner} sessionId={selectedId} />
      </div>
    </Dialog>
  );
}
