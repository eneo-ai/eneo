"use client";

import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { HStack, Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { TextInput } from "@/components/astryx/text-input";
import { useMutation, useQueryClient, type InfiniteData } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";
import { flushSync } from "react-dom";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { browserApi } from "@/lib/api/browser";
import { invalidateConversationLists } from "@/lib/api/conversations";
import { unwrap } from "@/lib/api/errors";
import type { CursorPage } from "@/lib/api/pagination";
import { toastApiError } from "@/lib/api/toast";
import type { ChatPartner } from "@/lib/chat/types";

/** Query key of a partner's conversation history (an infinite, cursor-paged list). */
export function historyQueryKey(partner: Pick<ChatPartner, "type" | "id">) {
  return ["conversations", partner.type === "group-chat" ? "group-chat" : "assistant", partner.id];
}

/** Rename and delete for conversations of one partner. */
export function useSessionMutations(
  partner: Pick<ChatPartner, "type" | "id">,
  {
    onRenamed,
    onDeleted
  }: {
    onRenamed?: (id: string, name: string) => void;
    onDeleted?: (id: string) => void;
  } = {}
) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const historyKey = historyQueryKey(partner);
  const invalidate = () => invalidateConversationLists(queryClient, historyKey);

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

  return { rename, remove };
}

/**
 * Rename dialog (Astryx Dialog, form purpose) with a visible label; Enter
 * saves. An empty name shows at the field on save, which takes focus.
 */
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
  // The conversation whose save found the name empty.
  const [submittedFor, setSubmittedFor] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const value = draft && draft.id === session?.id ? draft.name : (session?.name ?? "");
  const problem =
    session && submittedFor === session.id && !value.trim() ? t("required_field") : null;
  const save = () => {
    if (pending || !session) return;
    if (!value.trim()) {
      // Rendered before focus moves, so the field is read with its error.
      flushSync(() => setSubmittedFor(session.id));
      inputRef.current?.focus();
      return;
    }
    onSave(value.trim());
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
              ref={inputRef}
              label={t("chat_history_name_label")}
              value={value}
              onChange={(next) => session && setDraft({ id: session.id, name: next })}
              onEnter={save}
              isRequired
              status={problem ? { type: "error", message: problem } : undefined}
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
                // Keeps focus while saving; a second press is ignored.
                isLoading={pending}
                isInterruptible
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
