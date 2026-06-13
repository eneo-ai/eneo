"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { MoreVertical, Pencil, Trash2, UserMinus, UserPlus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { useAppContext } from "@/components/providers/app-context";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { UserEditorDialog } from "./user-editor";
import type { AdminUser } from "./users";

export function UserActions({ user }: { user: AdminUser }) {
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
    onSuccess: invalidate,
    onError: (error) => toastApiError(error, t)
  });

  const deleteUser = useMutation({
    mutationFn: () =>
      unwrap(browserApi.DELETE("/api/v1/users/admin/{id}/", { params: { path: { id: user.id } } })),
    onSuccess: () => {
      invalidate();
      setShowDelete(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon" aria-label={t("actions")}>
            <MoreVertical className="size-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onSelect={() => setShowEdit(true)}>
            <Pencil className="size-4" /> {t("edit_user")}
          </DropdownMenuItem>
          {isActive ? (
            <DropdownMenuItem
              disabled={isSelf || setState.isPending}
              onSelect={() => setState.mutate("deactivate")}
            >
              <UserMinus className="size-4" /> {t("deactivate_user")}
            </DropdownMenuItem>
          ) : (
            <DropdownMenuItem
              disabled={setState.isPending}
              onSelect={() => setState.mutate("reactivate")}
            >
              <UserPlus className="size-4" /> {t("reactivate_user")}
            </DropdownMenuItem>
          )}
          <DropdownMenuItem
            variant="destructive"
            disabled={isSelf}
            onSelect={() => setShowDelete(true)}
          >
            <Trash2 className="size-4" /> {t("delete_user")}
          </DropdownMenuItem>
        </DropdownMenuContent>
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
