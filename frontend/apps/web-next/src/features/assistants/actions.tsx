import type { DropdownMenuOption } from "@astryxdesign/core/DropdownMenu";
import { MoreMenu } from "@astryxdesign/core/MoreMenu";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowDownToLine, ArrowUpToLine, FolderInput, Pencil, Trash2 } from "lucide-react";
import { useRouter } from "@/lib/navigation";
import { useTranslations } from "use-intl";
import type { ReactNode, RefObject } from "react";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { createResourceActions } from "@/components/composites/resource-action-scope";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { MoveResourceDialog } from "@/features/knowledge/move-dialog";
import { useRemovalMutation } from "@/features/spaces/removal";
import { useSpace } from "@/features/spaces/use-space";
import type { ChatAppItem } from "./assistants";
import { PublishDialog } from "./publish-dialog";
import { invalidateExpiringApiKeys } from "@/features/api-keys/api-keys";

function useSpaceInvalidation() {
  const { routeId } = useSpace();
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });
}

/** Edit, publish/unpublish, move and delete, as far as the user may. */
function chatAppMenuItems(
  t: ReturnType<typeof useTranslations>,
  permissions: string[],
  {
    published,
    onEdit,
    onPublish,
    onMove,
    onDelete
  }: {
    published: boolean;
    onEdit: () => void;
    onPublish: () => void;
    onMove?: () => void;
    onDelete: () => void;
  }
): DropdownMenuOption[] {
  return [
    ...(permissions.includes("edit")
      ? [{ label: t("edit"), icon: <Pencil aria-hidden="true" />, onClick: onEdit }]
      : []),
    ...(permissions.includes("publish")
      ? [
          published
            ? {
                label: t("unpublish"),
                icon: <ArrowDownToLine aria-hidden="true" />,
                onClick: onPublish
              }
            : {
                label: t("publish"),
                icon: <ArrowUpToLine aria-hidden="true" />,
                onClick: onPublish
              }
        ]
      : []),
    ...(permissions.includes("delete")
      ? [
          ...(onMove
            ? [{ label: t("move"), icon: <FolderInput aria-hidden="true" />, onClick: onMove }]
            : []),
          {
            label: t("delete"),
            icon: <Trash2 aria-hidden="true" />,
            variant: "destructive" as const,
            onClick: onDelete
          }
        ]
      : [])
  ];
}

type ChatAppAction = "publish" | "move" | "delete";

const { ResourceActionScope, useOpenResourceAction } = createResourceActions<
  ChatAppItem,
  ChatAppAction
>();

function publishRequest(item: ChatAppItem): Promise<unknown> {
  return item.type === "group-chat"
    ? unwrap(
        browserApi.POST("/api/v1/group-chats/{id}/publish/", {
          params: { path: { id: item.id }, query: { published: !item.published } }
        })
      )
    : unwrap(
        browserApi.POST("/api/v1/assistants/{id}/publish/", {
          params: { path: { id: item.id }, query: { published: !item.published } }
        })
      );
}

function deleteRequest(item: ChatAppItem): Promise<unknown> {
  return item.type === "group-chat"
    ? unwrap(browserApi.DELETE("/api/v1/group-chats/{id}/", { params: { path: { id: item.id } } }))
    : unwrap(browserApi.DELETE("/api/v1/assistants/{id}/", { params: { path: { id: item.id } } }));
}

/** The publish, move and delete dialogs of an assistant's or group chat's menu, held above the rows and cards that open them. */
function ChatAppActionDialog({
  kind,
  resource: item,
  onClose
}: {
  kind: ChatAppAction;
  resource: ChatAppItem;
  onClose: () => void;
}) {
  const t = useTranslations();
  const invalidate = useSpaceInvalidation();
  const queryClient = useQueryClient();
  const isGroupChat = item.type === "group-chat";

  const publish = useMutation({
    mutationFn: () => publishRequest(item),
    onSuccess: () => {
      void invalidate();
      if (!isGroupChat) void invalidateExpiringApiKeys(queryClient);
      onClose();
    },
    onError: (error) => toastApiError(error, t)
  });

  const move = useRemovalMutation({
    mutationFn: (targetSpaceId: string) =>
      unwrap(
        browserApi.POST("/api/v1/assistants/{id}/transfer/", {
          params: { path: { id: item.id } },
          body: { target_space_id: targetSpaceId }
        })
      ),
    refresh: invalidate,
    onRemoved: onClose
  });

  const remove = useRemovalMutation({
    mutationFn: () => deleteRequest(item),
    refresh: invalidate,
    onRemoved: onClose
  });

  const onOpenChange = (open: boolean) => {
    if (!open) onClose();
  };

  if (kind === "publish") {
    return (
      <PublishDialog
        open
        onOpenChange={onOpenChange}
        name={item.name}
        published={item.published ?? false}
        pending={publish.isPending}
        publishHint={isGroupChat ? undefined : t("api_keys_notifications_publish_assistant_hint")}
        onConfirm={() => publish.mutate()}
      />
    );
  }
  if (kind === "move") {
    return (
      <MoveResourceDialog
        open
        onOpenChange={onOpenChange}
        title={t("move_assistant")}
        hint={t("move_assistant_knowledge_hint")}
        confirmLabel={t("move_assistant")}
        pending={move.isPending}
        onMove={(targetSpaceId) => move.mutate(targetSpaceId)}
      />
    );
  }
  return (
    <ConfirmDialogControlled
      open
      onOpenChange={onOpenChange}
      title={isGroupChat ? t("delete_group_chat") : t("delete_assistant")}
      description={
        isGroupChat
          ? t("confirm_delete_group_chat", { groupChatName: item.name })
          : t("confirm_delete_assistant", { name: item.name })
      }
      confirmLabel={remove.isPending ? t("deleting") : t("delete")}
      pending={remove.isPending}
      onConfirm={() => remove.mutate()}
    />
  );
}

/**
 * Above a collection of assistants and group chats: what their menus open. A
 * turn across 768 px replaces the rows with cards and the open dialog stays.
 * `focusTarget` is where focus goes when the control that opened one is gone.
 */
export function ChatAppActionScope({
  focusTarget,
  children
}: {
  focusTarget: RefObject<HTMLElement | null>;
  children: ReactNode;
}) {
  return (
    <ResourceActionScope Dialog={ChatAppActionDialog} focusTarget={focusTarget}>
      {children}
    </ResourceActionScope>
  );
}

/** The menu of an assistant or group chat: edit, publish, move (assistants) and delete, as far as the user may. */
export function ChatAppActions({ item }: { item: ChatAppItem }) {
  const t = useTranslations();
  const router = useRouter();
  const { routeId } = useSpace();
  const open = useOpenResourceAction();
  const permissions = item.permissions ?? [];

  if (!permissions.some((permission) => ["edit", "publish", "delete"].includes(permission))) {
    return null;
  }

  const isGroupChat = item.type === "group-chat";
  return (
    <MoreMenu
      label={t("space_more_actions_for", { name: item.name })}
      alignment="end"
      items={chatAppMenuItems(t, permissions, {
        published: item.published ?? false,
        onEdit: () =>
          router.push(
            `/spaces/${routeId}/${isGroupChat ? "group-chats" : "assistants"}/${item.id}/edit`
          ),
        onPublish: () => open("publish", item),
        onMove: isGroupChat ? undefined : () => open("move", item),
        onDelete: () => open("delete", item)
      })}
    />
  );
}
