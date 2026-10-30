"use client";

import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { FormLayout } from "@astryxdesign/core/FormLayout";
import { HStack, Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { revealProblems } from "@/components/composites/field-problem";
import { DIALOG_TOP_ON_TOUCH } from "@/components/astryx/dialog-placement";
import { TextInput } from "@astryxdesign/core/TextInput";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "use-intl";
import { useRef, useState } from "react";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { browserApi } from "@/lib/api/browser";
import { invalidateConversationLists, patchConversationLists } from "@/lib/api/conversations";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import type { ChatPartner } from "@/lib/chat/types";

/** Query key of a partner's conversation history (an infinite, cursor-paged list). */
export function historyQueryKey(partner: Pick<ChatPartner, "type" | "id">) {
  return ["conversations", partner.type === "group-chat" ? "group-chat" : "assistant", partner.id];
}

/** Every partner's history list a conversation may be in (`historyQueryKey`). */
const historyLists = {
  predicate: ({ queryKey }: { queryKey: readonly unknown[] }) =>
    queryKey[0] === "conversations" && (queryKey[1] === "assistant" || queryKey[1] === "group-chat")
};

/**
 * Rename and delete for conversations: of one partner, or under "Alla" of
 * any, so every history list and recent list hears of it.
 */
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
  const invalidate = () =>
    Promise.all([
      invalidateConversationLists(queryClient, historyQueryKey(partner)),
      queryClient.invalidateQueries(historyLists)
    ]);

  const rename = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      unwrap(
        browserApi.PATCH("/api/v1/conversations/{session_id}/name/", {
          params: { path: { session_id: id } },
          body: { name }
        })
      ),
    onSuccess: (_, { id, name }) => {
      patchConversationLists(queryClient, historyLists, id, name);
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
      patchConversationLists(queryClient, historyLists, id, null);
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
  // Tie local state to this opening of the dialog, not just the conversation id.
  // Reopening the same conversation must start from its current saved name.
  const [draft, setDraft] = useState<{ session: typeof session; name: string } | null>(null);
  const [submittedFor, setSubmittedFor] = useState<typeof session>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const value = draft?.session === session ? draft.name : (session?.name ?? "");
  const problem = session && submittedFor === session && !value.trim() ? t("required_field") : null;
  const close = () => {
    setDraft(null);
    setSubmittedFor(null);
    onCancel();
  };
  const save = () => {
    if (pending || !session) return;
    if (!value.trim()) {
      revealProblems(() => setSubmittedFor(session), inputRef.current);
      return;
    }
    onSave(value.trim());
  };

  return (
    <Dialog
      isOpen={session !== null}
      onOpenChange={(open) => !open && close()}
      purpose="form"
      width={440}
      className={DIALOG_TOP_ON_TOUCH}
    >
      <Layout
        header={
          <DialogHeader
            title={t("chat_history_rename")}
            subtitle={t("chat_history_rename_description")}
            onOpenChange={(open) => !open && close()}
          />
        }
        content={
          <LayoutContent>
            {/* Required is the default and unmarked (decision 40). */}
            <FormLayout defaultOptionality="required">
              <TextInput
                ref={inputRef}
                label={t("chat_history_name_label")}
                value={value}
                onChange={(next) => session && setDraft({ session, name: next })}
                onEnter={save}
                isRequired
                status={problem ? { type: "error", message: problem } : undefined}
              />
            </FormLayout>
          </LayoutContent>
        }
        footer={
          <LayoutFooter>
            <HStack gap={2} hAlign="end">
              <Button label={t("cancel")} variant="secondary" onClick={close} />
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
