import { useAnnounce } from "@astryxdesign/core/hooks";
import { IconButton } from "@astryxdesign/core/IconButton";
import { List, ListItem } from "@astryxdesign/core/List";
import {
  useInfiniteQuery,
  useMutation,
  useQueryClient,
  type InfiniteData
} from "@tanstack/react-query";
import { Sparkles, Trash2 } from "lucide-react";
import { useTranslations } from "use-intl";
import { useEffect, useId, useRef, useState } from "react";
import { ClientTime } from "@/components/composites/client-time";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { ListError, LoadMore } from "@/components/composites/query-state";
import { flattenPages } from "@/lib/api/pagination";
import { toastApiError } from "@/lib/api/toast";
import { useFocusRescue } from "@/lib/focus-rescue";
import {
  deleteInsightConversation,
  insightChatKeys,
  insightConversationsQueryOptions,
  type InsightConversationPage,
  type InsightConversationSummary,
  type InsightTarget
} from "./insights-chat-api";

/**
 * "Tidigare analyser": the operator's own analyses of this assistant or
 * group chat, newest first and a page at a time. A row opens its analysis to
 * read and continue; its delete button asks first (irreversible, WCAG
 * 3.3.4). Shown once there is one: an operator without any sees the
 * question field alone.
 */
export function InsightsHistory({
  target,
  onOpen
}: {
  target: InsightTarget;
  onOpen: (sessionId: string) => void;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const queryClient = useQueryClient();
  const rescue = useFocusRescue();
  const headingId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [deleting, setDeleting] = useState<InsightConversationSummary | null>(null);
  const history = useInfiniteQuery(insightConversationsQueryOptions(target));
  const pages = history.data?.pages;
  const rows = flattenPages(pages);
  const listRef = useRef<HTMLDivElement>(null);

  // "Visa fler analyser": once the page it asked for renders, focus that page's
  // first analysis (the button itself goes away with the last page).
  const focusPage = useRef<number | null>(null);
  const pageCount = pages?.length ?? 0;
  useEffect(() => {
    const page = focusPage.current;
    if (page === null || pageCount <= page) return;
    focusPage.current = null;
    const first = pages?.[page]?.items[0];
    if (!first) return;
    listRef.current
      ?.querySelector<HTMLElement>(`[data-insight-row="${CSS.escape(first.id)}"] button`)
      ?.focus();
  }, [pageCount, pages]);

  const remove = useMutation({
    mutationFn: (sessionId: string) => deleteInsightConversation(sessionId),
    onSuccess: (_, sessionId) => {
      // Gone from every loaded page at once; the refetch follows.
      queryClient.setQueryData<InfiniteData<InsightConversationPage, string | undefined>>(
        insightChatKeys.list(target),
        (data) =>
          data && {
            ...data,
            pages: data.pages.map((page) => ({
              ...page,
              items: page.items.filter((item) => item.id !== sessionId)
            }))
          }
      );
      void queryClient.invalidateQueries({ queryKey: insightChatKeys.list(target) });
      setDeleting(null);
      announce(t("insights_chat_deleted"));
      // The row and its delete button are gone: focus goes to the list's heading.
      rescue(headingRef.current);
    },
    onError: (error) => toastApiError(error, t)
  });

  // Shown from the first analysis on; one deleted down to none says so in its place.
  const [shown, setShown] = useState(false);
  if (rows.length > 0 && !shown) setShown(true);
  if (!shown && !(history.isError && rows.length === 0)) return null;

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-2">
      {/* Under the analysis panel's title (h2). */}
      <h3
        id={headingId}
        ref={headingRef}
        tabIndex={-1}
        className="text-base font-semibold focus:outline-none"
      >
        {t("insights_chat_history_heading")}
      </h3>
      {history.isError && rows.length === 0 ? (
        <ListError
          error={history.error}
          compact
          isRetrying={history.isFetching}
          onRetry={() => void history.refetch()}
        />
      ) : rows.length === 0 ? (
        <p className="text-ax-text-secondary text-sm">{t("insights_chat_history_empty")}</p>
      ) : (
        <div ref={listRef} className="flex flex-col gap-2">
          <List hasDividers edge="outset">
            {rows.map((row) => {
              const name = row.name.trim() || t("chat_history_untitled");
              const stamp = row.updated_at ?? row.created_at;
              return (
                <ListItem
                  key={row.id}
                  data-insight-row={row.id}
                  label={name}
                  description={stamp ? <ClientTime value={stamp} format="auto" /> : undefined}
                  startContent={
                    <span className="flex size-9 shrink-0 items-center justify-center">
                      <Sparkles aria-hidden="true" className="text-ax-text-secondary size-5" />
                    </span>
                  }
                  onClick={() => onOpen(row.id)}
                  endContent={
                    <IconButton
                      label={t("insights_chat_delete_named", { name })}
                      icon={<Trash2 aria-hidden="true" />}
                      variant="ghost"
                      size="sm"
                      onClick={() => setDeleting(row)}
                    />
                  }
                />
              );
            })}
          </List>
          <LoadMore
            query={history}
            label={t("insights_chat_history_load_more")}
            onLoad={() => {
              focusPage.current = pageCount;
              void history.fetchNextPage();
            }}
          />
        </div>
      )}
      <ConfirmDialogControlled
        open={deleting !== null}
        onOpenChange={(open) => {
          if (!open) setDeleting(null);
        }}
        title={t("insights_chat_delete_title")}
        description={deleting?.name ?? ""}
        confirmLabel={t("delete")}
        pending={remove.isPending}
        onConfirm={() => {
          if (deleting) remove.mutate(deleting.id);
        }}
      />
    </section>
  );
}
