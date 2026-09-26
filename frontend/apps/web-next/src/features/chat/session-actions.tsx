"use client";

import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { HStack, Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { TextInput } from "@astryxdesign/core/TextInput";
import { useMutation, useQueryClient, type InfiniteData } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { CursorPage } from "@/lib/api/pagination";
import { toastApiError } from "@/lib/api/toast";
import type { ChatPartner } from "@/lib/chat/types";

/** Query key of a partner's conversation history (an infinite, cursor-paged list). */
export function historyQueryKey(partner: Pick<ChatPartner, "type" | "id">) {
  return ["conversations", partner.type === "group-chat" ? "group-chat" : "assistant", partner.id];
}

/** Rename, delete and session feedback for conversations of one partner. */
export function useSessionMutations(
  partner: Pick<ChatPartner, "type" | "id">,
  {
    onRenamed,
    onDeleted,
    onRated
  }: {
    onRenamed?: (id: string, name: string) => void;
    onDeleted?: (id: string) => void;
    onRated?: (id: string, value: 1 | -1) => void;
  } = {}
) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const historyKey = historyQueryKey(partner);
  const invalidate = () => queryClient.invalidateQueries({ queryKey: historyKey });

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
      // Drop the row at once (the refetch follows), so the history never shows
      // a deleted conversation and focus can move on from its row.
      queryClient.setQueryData<InfiniteData<CursorPage<{ id: string }>>>(historyKey, (data) =>
        data
          ? {
              ...data,
              pages: data.pages.map((page) => ({
                ...page,
                items: page.items.filter((item) => item.id !== id)
              }))
            }
          : data
      );
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
    onSuccess: (_, { id, value }) => {
      toast.success(t("chat_feedback_thanks"));
      onRated?.(id, value);
    },
    onError: (error) => toastApiError(error, t)
  });

  return { rename, remove, feedback };
}

/** Rename dialog (Astryx Dialog, form purpose) with a visible label; Enter saves. */
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
  const [draft, setDraft] = useState<{ id: string; name: string } | null>(null);
  const value = draft && draft.id === session?.id ? draft.name : (session?.name ?? "");
  const save = () => {
    if (value.trim() && !pending) onSave(value.trim());
  };

  return (
    <Dialog
      isOpen={session !== null}
      onOpenChange={(open) => !open && onCancel()}
      purpose="form"
      width={440}
    >
      <Layout
        header={
          <DialogHeader
            title={t("chat_history_rename")}
            subtitle={t("chat_history_rename_description")}
            onOpenChange={(open) => !open && onCancel()}
          />
        }
        content={
          <LayoutContent>
            <TextInput
              label={t("chat_history_name_label")}
              value={value}
              onChange={(next) => session && setDraft({ id: session.id, name: next })}
              onEnter={save}
            />
          </LayoutContent>
        }
        footer={
          <LayoutFooter>
            <HStack gap={2} hAlign="end">
              <Button label={t("cancel")} variant="secondary" onClick={onCancel} />
              <Button
                label={t("save")}
                variant="primary"
                isDisabled={!value.trim() || pending}
                onClick={save}
              />
            </HStack>
          </LayoutFooter>
        }
      />
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
