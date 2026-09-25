"use client";

import { BottomSheet } from "@astryxdesign/core/BottomSheet";
import { Button as AxButton } from "@astryxdesign/core/Button";
import { IconButton } from "@astryxdesign/core/IconButton";
import { MoreMenu } from "@astryxdesign/core/MoreMenu";
import { X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useId, useRef, useState, type Ref } from "react";
import { LoadingState } from "@/components/composites/loading-state";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { ChatPartner } from "@/lib/chat/types";
import { usePaginatedQuery } from "@/lib/hooks/use-paginated-query";
import { cn } from "@/lib/utils";
import { historyBucket, type HistoryBucket } from "./format";
import {
  DeleteSessionDialog,
  historyQueryKey,
  RenameSessionDialog,
  useSessionMutations
} from "./session-actions";
import { useNow } from "./use-now";

export { historyQueryKey } from "./session-actions";

type SessionRow = {
  id: string;
  name: string;
  created_at?: string | null;
  updated_at?: string | null;
};

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
 * The partner's conversation history, grouped by date (Idag, Igår, …). Each
 * row opens the conversation; its menu renames, rates or deletes it.
 */
function HistoryPanel({
  partner,
  activeSessionId,
  onSelect,
  onDeleted,
  onRenamed,
  onClose,
  headingRef
}: {
  partner: ChatPartner;
  activeSessionId: string | null;
  onSelect: (sessionId: string) => void;
  onDeleted: (sessionId: string) => void;
  onRenamed?: (sessionId: string, name: string) => void;
  onClose: () => void;
  headingRef?: Ref<HTMLHeadingElement>;
}) {
  const t = useTranslations();
  const titleId = useId();
  const now = useNow();
  const [renaming, setRenaming] = useState<{ id: string; name: string } | null>(null);
  const [deleting, setDeleting] = useState<{ id: string; name: string } | null>(null);
  const { rename, remove, feedback } = useSessionMutations(partner, {
    onRenamed: (id, name) => {
      setRenaming(null);
      onRenamed?.(id, name);
    },
    onDeleted: (id) => {
      setDeleting(null);
      onDeleted(id);
    }
  });

  const isGroupChat = partner.type === "group-chat";
  const history = usePaginatedQuery({
    queryKey: historyQueryKey(partner),
    limit: 50,
    fetchPage: async ({ cursor, limit }) =>
      unwrap(
        browserApi.GET("/api/v1/conversations/", {
          params: {
            query: {
              assistant_id: isGroupChat ? undefined : partner.id,
              group_chat_id: isGroupChat ? partner.id : undefined,
              limit,
              cursor: cursor ?? undefined
            }
          }
        })
      )
  });

  const groups = groupSessions(history.items, now);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-ax-border flex min-h-[52px] shrink-0 items-center justify-between gap-2 border-b ps-3.5 pe-2.5">
        <h2
          id={titleId}
          ref={headingRef}
          tabIndex={-1}
          className="text-[13px] font-semibold focus:outline-none"
        >
          {t("history")}
        </h2>
        <IconButton
          label={t("chat_history_close")}
          icon={<X className="size-4" />}
          variant="ghost"
          size="sm"
          onClick={onClose}
        />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {history.isPending ? (
          <LoadingState rows={6} className="p-2" />
        ) : history.items.length === 0 ? (
          <p className="text-ax-text-secondary p-2 text-[13px]">{t("chat_history_empty")}</p>
        ) : (
          groups.map((group, index) => (
            <section
              key={`${group.bucket}-${index}`}
              aria-label={group.bucket ? t(BUCKET_KEY[group.bucket]) : t("history")}
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
                        aria-current={active ? "true" : undefined}
                        onClick={() => onSelect(session.id)}
                        className={cn(
                          "focus-visible:outline-ring rounded-ax-element min-h-9 min-w-0 flex-1 truncate px-2.5 text-start text-[13px] focus-visible:outline-2 focus-visible:-outline-offset-2 pointer-coarse:min-h-11",
                          active ? "font-semibold" : "text-ax-text-secondary hover:text-ax-text"
                        )}
                      >
                        {session.name || t("chat_history_untitled")}
                      </button>
                      <MoreMenu
                        label={t("chat_history_actions", { name: session.name })}
                        size="sm"
                        alignment="end"
                        items={[
                          {
                            label: t("rename"),
                            onClick: () => setRenaming({ id: session.id, name: session.name })
                          },
                          {
                            label: t("chat_history_rate_good"),
                            onClick: () => feedback.mutate({ id: session.id, value: 1 })
                          },
                          {
                            label: t("chat_history_rate_bad"),
                            onClick: () => feedback.mutate({ id: session.id, value: -1 })
                          },
                          { type: "divider" },
                          {
                            label: t("delete"),
                            variant: "destructive",
                            onClick: () => setDeleting({ id: session.id, name: session.name })
                          }
                        ]}
                      />
                    </li>
                  );
                })}
              </ul>
            </section>
          ))
        )}
        {(history.hasPreviousPage || history.hasNextPage) && (
          <div className="flex justify-between gap-2 p-2">
            {history.hasPreviousPage ? (
              <AxButton
                label={t("chat_history_newer")}
                variant="ghost"
                size="sm"
                onClick={history.previousPage}
              />
            ) : (
              <span />
            )}
            {history.hasNextPage && (
              <AxButton
                label={t("load_more")}
                variant="ghost"
                size="sm"
                onClick={history.nextPage}
              />
            )}
          </div>
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

/**
 * History as a side panel (≥768px, focus moves to its heading, Escape closes)
 * or an Astryx bottom sheet on phones (modal: it traps focus and returns it).
 * The caller returns focus to the history button when the panel closes.
 */
export function HistoryAside({
  onClose,
  inline,
  ...props
}: Omit<Parameters<typeof HistoryPanel>[0], "headingRef"> & { inline: boolean }) {
  const t = useTranslations();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const asideRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (inline) headingRef.current?.focus();
  }, [inline]);

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
      <BottomSheet
        isOpen
        onOpenChange={(open) => !open && onClose()}
        label={t("history")}
        height="tall"
      >
        <HistoryPanel {...props} onClose={onClose} />
      </BottomSheet>
    );
  }

  return (
    <aside
      ref={asideRef}
      id="chat-history"
      aria-label={t("history")}
      className="bg-ax-sunken border-ax-border flex w-72 shrink-0 flex-col border-s"
    >
      <HistoryPanel {...props} onClose={onClose} headingRef={headingRef} />
    </aside>
  );
}
