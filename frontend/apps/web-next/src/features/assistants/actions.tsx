"use client";

import type { DropdownMenuOption } from "@astryxdesign/core/DropdownMenu";
import { MoreMenu } from "@astryxdesign/core/MoreMenu";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowDownToLine, ArrowUpToLine, FolderInput, Pencil, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { MoveResourceDialog } from "@/features/knowledge/move-dialog";
import { useRemovalMutation } from "@/features/spaces/removal";
import { useSpace } from "@/features/spaces/use-space";
import type { AssistantSparse, GroupChatSparse } from "./assistants";
import { PublishDialog } from "./publish-dialog";

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

export function AssistantActions({ assistant }: { assistant: AssistantSparse }) {
  const t = useTranslations();
  const router = useRouter();
  const { routeId } = useSpace();
  const invalidate = useSpaceInvalidation();
  const [showPublish, setShowPublish] = useState(false);
  const [showMove, setShowMove] = useState(false);
  const [showDelete, setShowDelete] = useState(false);
  const [moveResources, setMoveResources] = useState(false);

  const permissions = assistant.permissions ?? [];

  const publish = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.POST("/api/v1/assistants/{id}/publish/", {
          params: { path: { id: assistant.id }, query: { published: !assistant.published } }
        })
      ),
    onSuccess: () => {
      void invalidate();
      setShowPublish(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  const move = useRemovalMutation({
    mutationFn: (targetSpaceId: string) =>
      unwrap(
        browserApi.POST("/api/v1/assistants/{id}/transfer/", {
          params: { path: { id: assistant.id } },
          body: { target_space_id: targetSpaceId, move_resources: moveResources }
        })
      ),
    refresh: invalidate,
    onRemoved: () => setShowMove(false)
  });

  const deleteAssistant = useRemovalMutation({
    mutationFn: () =>
      unwrap(
        browserApi.DELETE("/api/v1/assistants/{id}/", { params: { path: { id: assistant.id } } })
      ),
    refresh: invalidate,
    onRemoved: () => setShowDelete(false)
  });

  if (!permissions.some((permission) => ["edit", "publish", "delete"].includes(permission))) {
    return null;
  }

  return (
    <>
      <MoreMenu
        label={t("space_more_actions_for", { name: assistant.name })}
        alignment="end"
        items={chatAppMenuItems(t, permissions, {
          published: assistant.published ?? false,
          onEdit: () => router.push(`/spaces/${routeId}/assistants/${assistant.id}/edit`),
          onPublish: () => setShowPublish(true),
          onMove: () => setShowMove(true),
          onDelete: () => setShowDelete(true)
        })}
      />
      <PublishDialog
        open={showPublish}
        onOpenChange={setShowPublish}
        name={assistant.name}
        published={assistant.published ?? false}
        pending={publish.isPending}
        publishHint={t("api_keys_notifications_publish_assistant_hint")}
        onConfirm={() => publish.mutate()}
      />
      <MoveResourceDialog
        open={showMove}
        onOpenChange={setShowMove}
        title={t("move_assistant")}
        hint={moveResources ? t("move_assistant_hint") : undefined}
        confirmLabel={t("move_assistant")}
        pending={move.isPending}
        onMove={(targetSpaceId) => move.mutate(targetSpaceId)}
      >
        <Label className="flex items-center justify-between gap-2 py-1 font-normal">
          {t("include_assistants_knowledge")}
          <Switch checked={moveResources} onCheckedChange={setMoveResources} />
        </Label>
      </MoveResourceDialog>
      <ConfirmDialogControlled
        open={showDelete}
        onOpenChange={setShowDelete}
        title={t("delete_assistant")}
        description={t("confirm_delete_assistant", { name: assistant.name })}
        confirmLabel={deleteAssistant.isPending ? t("deleting") : t("delete")}
        pending={deleteAssistant.isPending}
        onConfirm={() => deleteAssistant.mutate()}
      />
    </>
  );
}

export function GroupChatActions({ groupChat }: { groupChat: GroupChatSparse }) {
  const t = useTranslations();
  const router = useRouter();
  const { routeId } = useSpace();
  const invalidate = useSpaceInvalidation();
  const [showPublish, setShowPublish] = useState(false);
  const [showDelete, setShowDelete] = useState(false);

  const permissions = groupChat.permissions ?? [];

  const publish = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.POST("/api/v1/group-chats/{id}/publish/", {
          params: { path: { id: groupChat.id }, query: { published: !groupChat.published } }
        })
      ),
    onSuccess: () => {
      void invalidate();
      setShowPublish(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  const deleteGroupChat = useRemovalMutation({
    mutationFn: () =>
      unwrap(
        browserApi.DELETE("/api/v1/group-chats/{id}/", { params: { path: { id: groupChat.id } } })
      ),
    refresh: invalidate,
    onRemoved: () => setShowDelete(false)
  });

  if (!permissions.some((permission) => ["edit", "publish", "delete"].includes(permission))) {
    return null;
  }

  return (
    <>
      <MoreMenu
        label={t("space_more_actions_for", { name: groupChat.name })}
        alignment="end"
        items={chatAppMenuItems(t, permissions, {
          published: groupChat.published,
          onEdit: () => router.push(`/spaces/${routeId}/group-chats/${groupChat.id}/edit`),
          onPublish: () => setShowPublish(true),
          onDelete: () => setShowDelete(true)
        })}
      />
      <PublishDialog
        open={showPublish}
        onOpenChange={setShowPublish}
        name={groupChat.name}
        published={groupChat.published}
        pending={publish.isPending}
        onConfirm={() => publish.mutate()}
      />
      <ConfirmDialogControlled
        open={showDelete}
        onOpenChange={setShowDelete}
        title={t("delete_group_chat")}
        description={t("confirm_delete_group_chat", { groupChatName: groupChat.name })}
        confirmLabel={deleteGroupChat.isPending ? t("deleting") : t("delete")}
        pending={deleteGroupChat.isPending}
        onConfirm={() => deleteGroupChat.mutate()}
      />
    </>
  );
}

export function ChatAppActions({ item }: { item: AssistantSparse | GroupChatSparse }) {
  if (item.type === "group-chat") return <GroupChatActions groupChat={item} />;
  return <AssistantActions assistant={item} />;
}
