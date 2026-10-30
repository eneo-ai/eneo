"use client";

import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "use-intl";
import { useId, useRef, useState } from "react";
import { TextInput } from "@astryxdesign/core/TextInput";
import { revealProblems } from "@/components/composites/field-problem";
import { useReturnFocus } from "@/components/ui/dialog-focus";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { toast } from "@/lib/toast";
import { refreshUserGroups, type UserGroup } from "./user-groups";

/**
 * The group's name. An empty one is explained at the field on save, which
 * takes focus (WCAG 3.3.1); the save button is never disabled, and busy it
 * keeps focus while a second press is ignored.
 */
function UserGroupForm({
  formId,
  group,
  onSaved,
  onPendingChange
}: {
  formId: string;
  /** Omitted: create mode. */
  group?: UserGroup;
  onSaved: () => void;
  onPendingChange: (pending: boolean) => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [name, setName] = useState(group?.name ?? "");
  const [submitted, setSubmitted] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);
  const problem = name.trim() ? null : t("required_field");

  const save = useMutation({
    mutationFn: (body: { name: string }) =>
      group
        ? unwrap(
            browserApi.POST("/api/v1/user-groups/{id}/", {
              params: { path: { id: group.id } },
              body
            })
          )
        : unwrap(browserApi.POST("/api/v1/user-groups/", { body })),
    onMutate: () => onPendingChange(true),
    onSettled: () => onPendingChange(false),
    onSuccess: (saved) => {
      void refreshUserGroups(queryClient);
      toast.success(
        group
          ? t("admin_user_groups_renamed", { name: saved.name })
          : t("admin_user_groups_created", { name: saved.name })
      );
      onSaved();
    },
    onError: (error) => toastApiError(error, t)
  });

  function submit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (save.isPending) return;
    if (problem) {
      revealProblems(() => setSubmitted(true), nameRef.current);
      return;
    }
    save.mutate({ name: name.trim() });
  }

  return (
    <form id={formId} onSubmit={submit} noValidate className="flex flex-col gap-4">
      <TextInput
        ref={nameRef}
        label={t("group_name")}
        description={t("descriptive_name_for_group")}
        value={name}
        onChange={setName}
        isRequired
        autoComplete="off"
        status={submitted && problem ? { type: "error", message: problem } : undefined}
        width="100%"
      />
    </form>
  );
}

/** Create a user group, or rename `group`. */
export function UserGroupDialog({
  group,
  open,
  onOpenChange
}: {
  /** The group to rename; null creates one. */
  group: UserGroup | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();
  const formId = useId();
  const [pending, setPending] = useState(false);
  // Rename is opened from a row menu, whose item is gone by the time the
  // dialog is up: focus goes back to the menu button.
  const noTrigger = useRef<HTMLElement | null>(null);
  useReturnFocus(open, noTrigger);

  function requestOpenChange(next: boolean) {
    if (!next && pending) return;
    onOpenChange(next);
  }

  return (
    <Dialog isOpen={open} onOpenChange={requestOpenChange} purpose="form" width={520}>
      <Layout
        height="auto"
        header={
          <DialogHeader
            title={group ? t("rename_user_group") : t("create_new_user_group")}
            onOpenChange={requestOpenChange}
          />
        }
        content={
          open ? (
            <LayoutContent>
              <UserGroupForm
                key={group?.id ?? "new"}
                formId={formId}
                group={group ?? undefined}
                onSaved={() => onOpenChange(false)}
                onPendingChange={setPending}
              />
            </LayoutContent>
          ) : null
        }
        footer={
          open ? (
            <LayoutFooter>
              <div className="flex flex-wrap items-center justify-end gap-2">
                <Button
                  label={t("cancel")}
                  isDisabled={pending}
                  onClick={() => requestOpenChange(false)}
                />
                <Button
                  type="submit"
                  form={formId}
                  variant="primary"
                  label={group ? t("save_changes") : t("create_user_group")}
                  isLoading={pending}
                  isInterruptible
                />
              </div>
            </LayoutFooter>
          ) : null
        }
      />
    </Dialog>
  );
}
