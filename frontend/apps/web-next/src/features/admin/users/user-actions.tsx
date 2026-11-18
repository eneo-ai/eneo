import {
  DropdownMenu,
  DropdownMenuDivider,
  DropdownMenuItem
} from "@astryxdesign/core/DropdownMenu";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { MoreHorizontal, Pencil, Trash2, UserMinus, UserPlus } from "lucide-react";
import { useTranslations } from "use-intl";
import { createContext, use, type ReactNode, type RefObject } from "react";
import { useAppContext } from "@/components/providers/app-context";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { createResourceActions } from "@/components/composites/resource-action-scope";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { toast } from "@/lib/toast";
import { UserEditorDialog, type IssuedPassword } from "./user-editor";
import type { AdminUser } from "./users";

type UserAction = "edit" | "delete";

const { ResourceActionScope, useOpenResourceAction } = createResourceActions<
  AdminUser,
  UserAction
>();

/** Where a password the editor set goes: the page's one-time view. */
const IssuedContext = createContext<(issued: IssuedPassword) => void>(() => {});

/** The edit and delete dialogs of a user's menu, held above the rows and table that open them. */
function UserActionDialog({
  kind,
  resource: user,
  onClose
}: {
  kind: UserAction;
  resource: AdminUser;
  onClose: () => void;
}) {
  const t = useTranslations();
  const onIssued = use(IssuedContext);
  const queryClient = useQueryClient();
  const onOpenChange = (open: boolean) => {
    if (!open) onClose();
  };

  const deleteUser = useMutation({
    mutationFn: () =>
      unwrap(browserApi.DELETE("/api/v1/users/admin/{id}/", { params: { path: { id: user.id } } })),
    onSuccess: async () => {
      toast.success(t("admin_users_deleted", { email: user.email }));
      // The row has gone once the list is back; closing then moves focus to the list.
      await queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      onClose();
    },
    onError: (error) => toastApiError(error, t)
  });

  if (kind === "edit") {
    return <UserEditorDialog open onOpenChange={onOpenChange} user={user} onIssued={onIssued} />;
  }
  return (
    <ConfirmDialogControlled
      open
      onOpenChange={onOpenChange}
      title={t("delete_user")}
      description={`${t("do_you_really_want_to_delete")} ${user.email}?`}
      confirmLabel={deleteUser.isPending ? t("deleting") : t("delete")}
      pending={deleteUser.isPending}
      onConfirm={() => deleteUser.mutate()}
    />
  );
}

/**
 * Above the users list: what its menus open. On a turn across 768 px the
 * rows and the table swap, and an open editor stays with what was typed in it.
 * `focusTarget` is where focus goes when the menu that opened one is gone.
 */
export function UserActionScope({
  focusTarget,
  onIssued,
  children
}: {
  focusTarget: RefObject<HTMLElement | null>;
  /** A password the editor set, for the page's one-time view. */
  onIssued: (issued: IssuedPassword) => void;
  children: ReactNode;
}) {
  return (
    <IssuedContext value={onIssued}>
      <ResourceActionScope Dialog={UserActionDialog} focusTarget={focusTarget}>
        {children}
      </ResourceActionScope>
    </IssuedContext>
  );
}

/**
 * Row menu for one user: edit, deactivate or reactivate, delete. The row
 * leaves the current tab after a state change, so `onRemoved` lets the page
 * put focus somewhere sensible once the list has refetched.
 */
export function UserActions({ user, onRemoved }: { user: AdminUser; onRemoved?: () => void }) {
  const t = useTranslations();
  const { user: currentUser } = useAppContext();
  const queryClient = useQueryClient();
  const open = useOpenResourceAction();

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

  return (
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
      <DropdownMenuItem icon={Pencil} label={t("edit_user")} onClick={() => open("edit", user)} />
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
        onClick={() => open("delete", user)}
      />
    </DropdownMenu>
  );
}
