"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import type { ChatPartner } from "@/lib/chat/types";

export function historyQueryKey(partner: Pick<ChatPartner, "type" | "id">) {
  return ["conversations", partner.type === "group-chat" ? "group-chat" : "assistant", partner.id];
}

/** Rename, delete and session feedback for conversations of one partner. */
export function useSessionMutations(
  partner: Pick<ChatPartner, "type" | "id">,
  {
    onRenamed,
    onDeleted
  }: { onRenamed?: (id: string, name: string) => void; onDeleted?: (id: string) => void } = {}
) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const invalidate = () => queryClient.invalidateQueries({ queryKey: historyQueryKey(partner) });

  const rename = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      unwrap(
        browserApi.PATCH("/api/v1/conversations/{session_id}/name/", {
          params: { path: { session_id: id } },
          body: { name }
        })
      ),
    onSuccess: (_, { id, name }) => {
      invalidate();
      onRenamed?.(id, name);
    },
    onError: (error) => toastApiError(error, t)
  });

  const remove = useMutation({
    mutationFn: (id: string) =>
      unwrap(
        browserApi.DELETE("/api/v1/conversations/{session_id}/", {
          params: { path: { session_id: id } }
        })
      ),
    onSuccess: (_, id) => {
      invalidate();
      onDeleted?.(id);
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

  return { rename, remove, feedback };
}

/** Rename dialog with a visible label (WCAG 3.3.2); Enter saves. */
export function RenameSessionDialog({
  session,
  pending,
  onCancel,
  onSave
}: {
  session: { id: string; name: string } | null;
  pending: boolean;
  onCancel: () => void;
  onSave: (name: string) => void;
}) {
  const t = useTranslations();
  const inputId = useId();
  const descriptionId = useId();
  const [draft, setDraft] = useState<{ id: string; name: string } | null>(null);
  const value = draft && draft.id === session?.id ? draft.name : (session?.name ?? "");

  return (
    <Dialog open={session !== null} onOpenChange={(open) => !open && onCancel()}>
      <DialogContent>
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (value.trim() && !pending) onSave(value.trim());
          }}
        >
          <DialogHeader>
            <DialogTitle>{t("chat_history_rename")}</DialogTitle>
            <DialogDescription id={descriptionId}>
              {t("chat_history_rename_description")}
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={inputId}>{t("chat_history_name_label")}</Label>
            <Input
              id={inputId}
              value={value}
              aria-describedby={descriptionId}
              onChange={(event) =>
                session && setDraft({ id: session.id, name: event.target.value })
              }
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onCancel}>
              {t("cancel")}
            </Button>
            <Button type="submit" disabled={!value.trim() || pending}>
              {t("save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Confirmation before deleting a conversation (irreversible, WCAG 3.3.4). */
export function DeleteSessionDialog({
  session,
  pending,
  onCancel,
  onConfirm
}: {
  session: { id: string; name: string } | null;
  pending: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const t = useTranslations();
  return (
    <ConfirmDialogControlled
      open={session !== null}
      onOpenChange={(open) => !open && onCancel()}
      title={t("chat_delete_conversation")}
      description={session?.name ?? ""}
      confirmLabel={t("confirm_deletion")}
      pending={pending}
      onConfirm={onConfirm}
    />
  );
}
