"use client";

import {
  DropdownMenu,
  DropdownMenuDivider,
  DropdownMenuItem
} from "@astryxdesign/core/DropdownMenu";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { MoreHorizontal, Pencil, Trash2, UserMinus, UserPlus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
import { useAppContext } from "@/components/providers/app-context";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { UserEditorDialog } from "./user-editor";
import type { AdminUser } from "./users";

/**
 * Row menu for one user: edit, deactivate or reactivate, delete. The row
 * leaves the current tab after a state change or delete, so `onRemoved` lets
 * the page put focus somewhere sensible once the list has refetched.
 */
export function UserActions({ user, onRemoved }: { user: AdminUser; onRemoved?: () => void }) {
  const t = useTranslations();
  const { user: currentUser } = useAppContext();
  const queryClient = useQueryClient();
  const [showEdit, setShowEdit] = useState(false);
  const [showDelete, setShowDelete] = useState(false);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["admin-users"] });
  const isSelf = user.id === currentUser.id;
  const isActive = user.state === "active" || user.state === "invited";

  const setState = useMutation({
    mutationFn: (action: "deactivate" | "reactivate") => {
      if (!user.username) throw new Error("missing username");
      const path =
        action === "deactivate"
          ? ("/api/v1/admin/users/{username}/deactivate" as const)
          : ("/api/v1/admin/users/{username}/reactivate" as const);
      return unwrap(browserApi.POST(path, { params: { path: { username: user.username } } }));
    },
    onSuccess: async (_data, action) => {
      toast.success(
        action === "deactivate"
          ? t("admin_users_deactivated", { email: user.email })
          : t("admin_users_reactivated", { email: user.email })
      );
      await invalidate();
      onRemoved?.();
    },
    onError: (error) => toastApiError(error, t)
  });

  const deleteUser = useMutation({
    mutationFn: () =>
      unwrap(browserApi.DELETE("/api/v1/users/admin/{id}/", { params: { path: { id: user.id } } })),
    onSuccess: async () => {
      setShowDelete(false);
      toast.success(t("admin_users_deleted", { email: user.email }));
      await invalidate();
      onRemoved?.();
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <>
      <DropdownMenu
        button={{
          label: t("admin_users_row_menu", { email: user.email }),
          tooltip: t("admin_users_row_menu", { email: user.email }),
          icon: <MoreHorizontal className="size-4" aria-hidden="true" />,
          isIconOnly: true,
          variant: "ghost",
          size: "sm"
        }}
        hasChevron={false}
        alignment="end"
      >
        <DropdownMenuItem icon={Pencil} label={t("edit_user")} onClick={() => setShowEdit(true)} />
        {isActive ? (
          <DropdownMenuItem
            icon={UserMinus}
            label={t("deactivate_user")}
            isDisabled={isSelf || setState.isPending}
            onClick={() => setState.mutate("deactivate")}
          />
        ) : (
          <DropdownMenuItem
            icon={UserPlus}
            label={t("reactivate_user")}
            isDisabled={setState.isPending}
            onClick={() => setState.mutate("reactivate")}
          />
        )}
        <DropdownMenuDivider />
        <DropdownMenuItem
          icon={Trash2}
          label={t("delete_user")}
          variant="destructive"
          isDisabled={isSelf}
          onClick={() => setShowDelete(true)}
        />
      </DropdownMenu>

      <UserEditorDialog open={showEdit} onOpenChange={setShowEdit} user={user} />
      <ConfirmDialogControlled
        open={showDelete}
        onOpenChange={setShowDelete}
        title={t("delete_user")}
        description={`${t("do_you_really_want_to_delete")} ${user.email}?`}
        confirmLabel={deleteUser.isPending ? t("deleting") : t("delete")}
        pending={deleteUser.isPending}
        onConfirm={() => deleteUser.mutate()}
      />
    </>
  );
}
