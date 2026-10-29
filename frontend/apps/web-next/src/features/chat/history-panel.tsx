"use client";

import { BottomSheet } from "@astryxdesign/core/BottomSheet";
import { IconButton } from "@astryxdesign/core/IconButton";
import { MoreMenu } from "@astryxdesign/core/MoreMenu";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Search, X } from "lucide-react";
import { useRouter } from "@/lib/navigation";
import { useTranslations } from "use-intl";
import { useEffect, useId, useRef, useState } from "react";
import { TextInput } from "@/components/astryx/text-input";
import { LoadMore, QueryStateBoundary } from "@/components/composites/query-state";
import { conversationContext } from "@/components/shell/conversation-context";
import { conversationHref } from "@/components/shell/routes";
import { browserApi } from "@/lib/api/browser";
import {
  ALL_CONVERSATIONS_LIMIT,
  recentConversationsQueryOptions,
  type RecentConversation
} from "@/lib/api/conversations";
import { unwrap } from "@/lib/api/errors";
import { cursorPagination, flattenPages } from "@/lib/api/pagination";
import { displayPartnerName } from "@/lib/chat/partner-name";
import type { ChatPartner } from "@/lib/chat/types";
import { useFocusRescue } from "@/lib/focus-rescue";
import { matchesSearch, searchTerms } from "@/lib/search";
import { cn } from "@/lib/utils";
import { historyBucket, type HistoryBucket } from "./format";
import {
  DeleteSessionDialog,
  historyQueryKey,
  RenameSessionDialog,
  useSessionMutations
} from "./session-actions";
import { useNow } from "./use-now";

const PAGE_SIZE = 50;

/** The history's width beside the conversation (in px, as the 480 px rule is). */
export const HISTORY_WIDTH = 320;

type SessionRow = {
  id: string;
  name: string;
  created_at?: string | null;
  updated_at?: string | null;
};

/** A listed conversation; under "Alla" it says whom it is with. */
type ListedSession = SessionRow & { with?: RecentConversation };

/** Under "Alla", the latest conversations with every assistant, as rows. */
const listed = (conversation: RecentConversation): ListedSession => ({
  id: conversation.id,
  name: conversation.name,
  created_at: conversation.created_at,
  updated_at: conversation.last_activity_at,
  with: conversation
});

const BUCKET_KEY = {
  today: "chat_history_today",
  yesterday: "chat_history_yesterday",
  week: "chat_history_week",
  month: "chat_history_month",
  older: "chat_history_older"
} as const satisfies Record<HistoryBucket, string>;

/** Consecutive date groups of a newest-first session list. */
export function groupSessions<T extends SessionRow>(
  sessions: T[],
  now: number | null
): { bucket: HistoryBucket | null; sessions: T[] }[] {
  if (now === null) return sessions.length > 0 ? [{ bucket: null, sessions }] : [];
  const today = new Date(now);
  const groups: { bucket: HistoryBucket | null; sessions: T[] }[] = [];
  for (const session of sessions) {
    const stamp = session.updated_at ?? session.created_at;
    const date = stamp ? new Date(stamp) : null;
    const bucket = date && !Number.isNaN(date.getTime()) ? historyBucket(date, today) : "older";
    const last = groups.at(-1);
    if (last && last.bucket === bucket) last.sessions.push(session);
    else groups.push({ bucket, sessions: [session] });
  }
  return groups;
}

/**
 * Conversations whose title contains every word of the query, over the pages
 * loaded so far; "Visa fler" stays available to search further back.
 */
export function filterSessions<T extends SessionRow>(
  sessions: T[],
  query: string,
  untitled: string
): T[] {
  if (searchTerms(query).length === 0) return sessions;
  return sessions.filter((session) => matchesSearch([session.name || untitled], query));
}

/**
 * "Konversationer" (decision 29): one panel, scoped to this assistant or
 * group chat, or to all of them ("Den här assistenten | Alla"), with a title
 * search at the top and the rows grouped by date (Idag, Igår, …). This
 * assistant's list is complete: "Visa fler" appends the next page and moves
 * focus to the first row it added. "Alla" lists the latest conversations
 * across assistants, each saying whom it is with; one with another assistant
 * opens where it lives. Each row's menu renames or deletes it.
 */
function HistoryPanel({
  partner,
  activeSessionId,
  onSelect,
  onDeleted,
  onRenamed,
  onClose,
  focusHeadingOnMount = false
}: {
  partner: ChatPartner;
  activeSessionId: string | null;
  onSelect: (sessionId: string) => void;
  onDeleted: (sessionId: string) => void;
  onRenamed?: (sessionId: string, name: string) => void;
  onClose: () => void;
  /** Side panel: focus moves to the heading when it opens. */
  focusHeadingOnMount?: boolean;
}) {
  const t = useTranslations();
  const router = useRouter();
  const titleId = useId();
  const now = useNow();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const rescue = useFocusRescue();
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<"partner" | "all">("partner");
  const [renaming, setRenaming] = useState<{ id: string; name: string } | null>(null);
  const [deleting, setDeleting] = useState<{ id: string; name: string } | null>(null);
  const partnerName = displayPartnerName(partner, t);
  const { rename, remove } = useSessionMutations(partner, {
    onRenamed: (id, name) => {
      setRenaming(null);
      onRenamed?.(id, name);
    },
    onDeleted: (id) => {
      setDeleting(null);
      // The deleted row (and the menu button the dialog returns focus to) is gone.
      rescue(headingRef.current);
      onDeleted(id);
    }
  });

  useEffect(() => {
    if (focusHeadingOnMount) headingRef.current?.focus();
  }, [focusHeadingOnMount]);

  const isGroupChat = partner.type === "group-chat";
  const history = useInfiniteQuery({
    ...cursorPagination,
    queryKey: historyQueryKey(partner),
    queryFn: ({ pageParam, signal }) =>
      unwrap(
        browserApi.GET("/api/v1/conversations/", {
          params: {
            query: {
              assistant_id: isGroupChat ? undefined : partner.id,
              group_chat_id: isGroupChat ? partner.id : undefined,
              limit: PAGE_SIZE,
              cursor: pageParam
            }
          },
          signal
        })
      )
  });
  const everyone = useQuery({
    ...recentConversationsQueryOptions(browserApi, ALL_CONVERSATIONS_LIMIT),
    enabled: scope === "all"
  });
  const all = scope === "all";
  const list = all ? everyone : history;
  const pages = history.data?.pages;
  const sessions: ListedSession[] = all ? (everyone.data ?? []).map(listed) : flattenPages(pages);
  const shown = filterSessions(sessions, query, t("chat_history_untitled"));
  const groups = groupSessions(shown, now);

  /** Opens a conversation: here when it is with this partner, else where it lives. */
  function open(session: ListedSession) {
    const other = session.with?.partner;
    if (other && (other.type !== partner.type || other.id !== partner.id)) {
      router.push(conversationHref(session.with!));
    } else {
      onSelect(session.id);
    }
  }

  // "Visa fler": once the page it asked for renders, focus that page's first
  // conversation (the button itself goes away with the last page).
  const focusPage = useRef<number | null>(null);
  const pageCount = pages?.length ?? 0;
  useEffect(() => {
    const page = focusPage.current;
    if (page === null || pageCount <= page) return;
    focusPage.current = null;
    const first = pages?.[page]?.items[0];
    if (!first) return;
    listRef.current
      ?.querySelector<HTMLElement>(`[data-session-row="${CSS.escape(first.id)}"]`)
      ?.focus();
  }, [pageCount, pages]);

  function loadMore() {
    focusPage.current = pageCount;
    void history.fetchNextPage();
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-ax-border flex min-h-[52px] shrink-0 items-center justify-between gap-2 border-b ps-3.5 pe-2.5">
        <h2
          id={titleId}
          ref={headingRef}
          tabIndex={-1}
          className="min-w-0 truncate text-[13px] font-semibold focus:outline-none"
        >
          {t("chat_history_title")}
        </h2>
        <IconButton
          label={t("chat_history_close")}
          icon={<X className="size-4" />}
          variant="ghost"
          size="sm"
          onClick={onClose}
        />
      </div>
      <div className="border-ax-border flex shrink-0 flex-col gap-2 border-b px-2 py-2">
        <SegmentedControl
          label={t("chat_history_scope")}
          value={scope}
          onChange={(value) => setScope(value === "all" ? "all" : "partner")}
          size="sm"
        >
          <SegmentedControlItem
            value="partner"
            label={
              isGroupChat ? t("chat_history_scope_group_chat") : t("chat_history_scope_assistant")
            }
          />
          <SegmentedControlItem value="all" label={t("chat_history_scope_all")} />
        </SegmentedControl>
        {sessions.length > 0 && (
          <TextInput
            label={t("chat_history_search")}
            isLabelHidden
            placeholder={t("chat_history_search")}
            value={query}
            onChange={setQuery}
            startIcon={Search}
            hasClear
            size="sm"
            width="100%"
          />
        )}
      </div>
      <div ref={listRef} className="min-h-0 flex-1 overflow-y-auto p-2">
        <QueryStateBoundary<unknown> query={list} rows={6}>
          {() =>
            sessions.length === 0 ? (
              <p className="text-ax-text-secondary p-2 text-[13px]">
                {all
                  ? t("chat_history_empty")
                  : t("chat_history_empty_with", { name: partnerName })}
              </p>
            ) : shown.length === 0 ? (
              <p className="text-ax-text-secondary p-2 text-[13px]">
                {t("chat_history_no_matches", { query: query.trim() })}
              </p>
            ) : (
              groups.map((group, index) => (
                <section
                  key={`${group.bucket}-${index}`}
                  aria-label={group.bucket ? t(BUCKET_KEY[group.bucket]) : t("chat_history_title")}
                  className="flex flex-col"
                >
                  {group.bucket && (
                    <h3 className="text-ax-text-secondary px-2 pt-3 pb-1 text-xs font-semibold first:pt-1">
                      {t(BUCKET_KEY[group.bucket])}
                    </h3>
                  )}
                  <ul className="flex flex-col gap-0.5">
                    {group.sessions.map((session) => {
                      const active = session.id === activeSessionId;
                      const name = session.name || t("chat_history_untitled");
                      const context = session.with
                        ? (conversationContext(session.with, t) ?? t("personal_assistant"))
                        : null;
                      return (
                        <li
                          key={session.id}
                          className={cn(
                            "rounded-ax-element flex items-center transition-colors",
                            active ? "bg-ax-selected" : "hover:bg-ax-hover"
                          )}
                        >
                          <button
                            type="button"
                            data-session-row={session.id}
                            aria-current={active ? "true" : undefined}
                            onClick={() => open(session)}
                            className={cn(
                              "focus-visible:outline-ring rounded-ax-element flex min-h-9 min-w-0 flex-1 flex-col justify-center px-2.5 py-1 text-start text-[13px] focus-visible:outline-2 focus-visible:-outline-offset-2 pointer-coarse:min-h-11",
                              active ? "font-semibold" : "text-ax-text-secondary hover:text-ax-text"
                            )}
                          >
                            <span className="w-full truncate">{name}</span>
                            {context && (
                              <span className="text-ax-text-secondary w-full truncate text-xs font-normal">
                                {context}
                              </span>
                            )}
                          </button>
                          <MoreMenu
                            label={t("chat_history_actions", { name })}
                            size="sm"
                            alignment="end"
                            items={[
                              {
                                label: t("rename"),
                                onClick: () => setRenaming({ id: session.id, name: session.name })
                              },
                              { type: "divider" },
                              {
                                label: t("delete"),
                                variant: "destructive",
                                onClick: () => setDeleting({ id: session.id, name })
                              }
                            ]}
                          />
                        </li>
                      );
                    })}
                  </ul>
                </section>
              ))
            )
          }
        </QueryStateBoundary>
        {!all && <LoadMore query={history} label={t("chat_history_load_more")} onLoad={loadMore} />}
      </div>

      {/* Outside the row menus: the menu closes before a dialog opens. */}
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

/**
 * History as a side panel (where the conversation keeps 480 px beside it; focus
 * moves to its heading, Escape closes) or an Astryx bottom sheet (modal: it
 * traps focus and returns it). The chat page decides which.
 * The caller returns focus to the history button when the panel closes.
 */
export function HistoryAside({
  onClose,
  inline,
  ...props
}: Omit<Parameters<typeof HistoryPanel>[0], "focusHeadingOnMount"> & { inline: boolean }) {
  const t = useTranslations();
  const asideRef = useRef<HTMLElement>(null);
  const label = t("chat_history_title");

  useEffect(() => {
    const aside = asideRef.current;
    if (!inline || !aside) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      event.preventDefault();
      onClose();
    };
    aside.addEventListener("keydown", onKeyDown);
    return () => aside.removeEventListener("keydown", onKeyDown);
  }, [inline, onClose]);

  if (!inline) {
    return (
      <BottomSheet isOpen onOpenChange={(open) => !open && onClose()} label={label} height="tall">
        <HistoryPanel {...props} onClose={onClose} />
      </BottomSheet>
    );
  }

  return (
    <aside
      ref={asideRef}
      id="chat-history"
      aria-label={label}
      style={{ width: HISTORY_WIDTH }}
      className="bg-ax-sunken border-ax-border flex shrink-0 flex-col border-s"
    >
      <HistoryPanel {...props} onClose={onClose} focusHeadingOnMount />
    </aside>
  );
}
