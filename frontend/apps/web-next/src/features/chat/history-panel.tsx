"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { MoreHorizontal, ThumbsDown, ThumbsUp } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { ConfirmDialog } from "@/components/composites/confirm-dialog";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { usePaginatedQuery } from "@/lib/hooks/use-paginated-query";
import { cn } from "@/lib/utils";
import type { ChatPartner } from "@/lib/chat/types";

export function historyQueryKey(partner: ChatPartner) {
  return ["conversations", partner.type === "group-chat" ? "group-chat" : "assistant", partner.id];
}

export function HistoryPanel({
  partner,
  activeSessionId,
  onSelect,
  onDeleted
}: {
  partner: ChatPartner;
  activeSessionId: string | null;
  onSelect: (sessionId: string) => void;
  onDeleted: (sessionId: string) => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [renaming, setRenaming] = useState<{ id: string; name: string } | null>(null);

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

  const invalidate = () => queryClient.invalidateQueries({ queryKey: historyQueryKey(partner) });

  const renameSession = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      unwrap(
        browserApi.PATCH("/api/v1/conversations/{session_id}/name/", {
          params: { path: { session_id: id } },
          body: { name }
        })
      ),
    onSuccess: () => {
      invalidate();
      setRenaming(null);
    },
    onError: (error) => toastApiError(error, t)
  });

  const deleteSession = useMutation({
    mutationFn: (id: string) =>
      unwrap(
        browserApi.DELETE("/api/v1/conversations/{session_id}/", {
          params: { path: { session_id: id } }
        })
      ),
    onSuccess: (_, id) => {
      invalidate();
      onDeleted(id);
    },
    onError: (error) => toastApiError(error, t)
  });

  const feedback = useMutation({
    mutationFn: ({ id, value }: { id: string; value: 1 | -1 }) =>
      unwrap(
        browserApi.POST("/api/v1/conversations/{session_id}/feedback/", {
          params: { path: { session_id: id } },
          body: { value }
        })
      ),
    onError: (error) => toastApiError(error, t)
  });

  return (
    <div className="flex h-full flex-col gap-2">
      <div className="text-muted-foreground px-2 pb-1 text-[11px] font-semibold tracking-wider uppercase">
        {t("conversations")}
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto">
        {history.items.map((session) => (
          <div
            key={session.id}
            className={cn(
              "group hover:bg-sidebar-accent/60 focus-within:bg-sidebar-accent/60 flex items-center rounded-lg transition-colors",
              session.id === activeSessionId &&
                "bg-sidebar-accent text-sidebar-accent-foreground hover:bg-sidebar-accent font-medium"
            )}
          >
            <button
              type="button"
              onClick={() => onSelect(session.id)}
              className="min-w-0 flex-1 truncate px-2.5 py-2 text-left text-[13px]"
              title={session.name}
            >
              {session.name}
            </button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-7 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100"
                  aria-label={t("actions")}
                >
                  <MoreHorizontal className="size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem
                  onClick={() => setRenaming({ id: session.id, name: session.name })}
                >
                  {t("rename")}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => feedback.mutate({ id: session.id, value: 1 })}>
                  <ThumbsUp /> +1
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => feedback.mutate({ id: session.id, value: -1 })}>
                  <ThumbsDown /> -1
                </DropdownMenuItem>
                <ConfirmDialog
                  trigger={
                    <DropdownMenuItem
                      variant="destructive"
                      onSelect={(event) => event.preventDefault()}
                    >
                      {t("delete")}
                    </DropdownMenuItem>
                  }
                  title={t("delete")}
                  description={session.name}
                  confirmLabel={t("confirm_deletion")}
                  pending={deleteSession.isPending}
                  onConfirm={() => deleteSession.mutateAsync(session.id).then(() => undefined)}
                />
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        ))}
        {history.hasNextPage && (
          <Button variant="ghost" size="sm" onClick={history.nextPage}>
            {t("load_more")}
          </Button>
        )}
      </div>

      <Dialog open={renaming !== null} onOpenChange={(open) => !open && setRenaming(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("rename")}</DialogTitle>
          </DialogHeader>
          <Input
            aria-label={t("rename")}
            value={renaming?.name ?? ""}
            onChange={(event) =>
              setRenaming((current) => current && { ...current, name: event.target.value })
            }
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setRenaming(null)}>
              {t("cancel")}
            </Button>
            <Button
              disabled={!renaming?.name.trim() || renameSession.isPending}
              onClick={() => renaming && renameSession.mutate(renaming)}
            >
              {t("save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
