"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDownToLine,
  ArrowUpToLine,
  FolderInput,
  MoreHorizontal,
  Pencil,
  Trash2
} from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { MoveResourceDialog } from "@/features/knowledge/move-dialog";
import { useSpace } from "@/features/spaces/use-space";
import type { AssistantSparse, GroupChatSparse } from "./assistants";
import { PublishDialog } from "./publish-dialog";

function useSpaceInvalidation() {
  const { routeId } = useSpace();
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });
}

export function AssistantActions({ assistant }: { assistant: AssistantSparse }) {
  const t = useTranslations();
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
      invalidate();
      setShowPublish(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  const move = useMutation({
    mutationFn: (targetSpaceId: string) =>
      unwrap(
        browserApi.POST("/api/v1/assistants/{id}/transfer/", {
          params: { path: { id: assistant.id } },
          body: { target_space_id: targetSpaceId, move_resources: moveResources }
        })
      ),
    onSuccess: () => {
      invalidate();
      setShowMove(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  const deleteAssistant = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.DELETE("/api/v1/assistants/{id}/", { params: { path: { id: assistant.id } } })
      ),
    onSuccess: () => {
      invalidate();
      setShowDelete(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  if (!permissions.some((permission) => ["edit", "publish", "delete"].includes(permission))) {
    return null;
  }

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon" aria-label={t("actions")}>
            <MoreHorizontal className="size-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {permissions.includes("edit") && (
            <DropdownMenuItem asChild>
              <Link href={`/spaces/${routeId}/assistants/${assistant.id}/edit`}>
                <Pencil className="size-4" /> {t("edit")}
              </Link>
            </DropdownMenuItem>
          )}
          {permissions.includes("publish") && (
            <DropdownMenuItem onSelect={() => setShowPublish(true)}>
              {assistant.published ? (
                <>
                  <ArrowDownToLine className="size-4" /> {t("unpublish")}
                </>
              ) : (
                <>
                  <ArrowUpToLine className="size-4" /> {t("publish")}
                </>
              )}
            </DropdownMenuItem>
          )}
          {permissions.includes("delete") && (
            <>
              <DropdownMenuItem onSelect={() => setShowMove(true)}>
                <FolderInput className="size-4" /> {t("move")}
              </DropdownMenuItem>
              <DropdownMenuItem variant="destructive" onSelect={() => setShowDelete(true)}>
                <Trash2 className="size-4" /> {t("delete")}
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
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
      invalidate();
      setShowPublish(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  const deleteGroupChat = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.DELETE("/api/v1/group-chats/{id}/", { params: { path: { id: groupChat.id } } })
      ),
    onSuccess: () => {
      invalidate();
      setShowDelete(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  if (!permissions.some((permission) => ["edit", "publish", "delete"].includes(permission))) {
    return null;
  }

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon" aria-label={t("actions")}>
            <MoreHorizontal className="size-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {permissions.includes("edit") && (
            <DropdownMenuItem asChild>
              <Link href={`/spaces/${routeId}/group-chats/${groupChat.id}/edit`}>
                <Pencil className="size-4" /> {t("edit")}
              </Link>
            </DropdownMenuItem>
          )}
          {permissions.includes("publish") && (
            <DropdownMenuItem onSelect={() => setShowPublish(true)}>
              {groupChat.published ? (
                <>
                  <ArrowDownToLine className="size-4" /> {t("unpublish")}
                </>
              ) : (
                <>
                  <ArrowUpToLine className="size-4" /> {t("publish")}
                </>
              )}
            </DropdownMenuItem>
          )}
          {permissions.includes("delete") && (
            <DropdownMenuItem variant="destructive" onSelect={() => setShowDelete(true)}>
              <Trash2 className="size-4" /> {t("delete")}
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
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
