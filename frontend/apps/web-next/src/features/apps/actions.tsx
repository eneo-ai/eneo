"use client";

import type { DropdownMenuOption } from "@astryxdesign/core/DropdownMenu";
import { MoreMenu } from "@astryxdesign/core/MoreMenu";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowDownToLine, ArrowUpToLine, Pencil, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { useRemovalMutation } from "@/features/spaces/removal";
import { useSpace } from "@/features/spaces/use-space";
import { PublishDialog } from "@/features/assistants/publish-dialog";
import type { AppSparse } from "./apps";

/** Edit/publish/delete menu for an app, shown on its tile. */
export function AppActions({ app }: { app: AppSparse }) {
  const t = useTranslations();
  const router = useRouter();
  const { routeId } = useSpace();
  const queryClient = useQueryClient();
  const [showPublish, setShowPublish] = useState(false);
  const [showDelete, setShowDelete] = useState(false);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });
  const permissions = app.permissions ?? [];

  const publish = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.POST("/api/v1/apps/{id}/publish/", {
          params: { path: { id: app.id }, query: { published: !app.published } }
        })
      ),
    onSuccess: () => {
      void invalidate();
      setShowPublish(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  const deleteApp = useRemovalMutation({
    mutationFn: () =>
      unwrap(browserApi.DELETE("/api/v1/apps/{id}/", { params: { path: { id: app.id } } })),
    refresh: invalidate,
    onRemoved: () => setShowDelete(false)
  });

  if (!permissions.some((permission) => ["edit", "publish", "delete"].includes(permission))) {
    return null;
  }

  const items: DropdownMenuOption[] = [
    ...(permissions.includes("edit")
      ? [
          {
            label: t("edit"),
            icon: <Pencil aria-hidden="true" />,
            onClick: () => router.push(`/spaces/${routeId}/apps/${app.id}/edit`)
          }
        ]
      : []),
    ...(permissions.includes("publish")
      ? [
          {
            label: app.published ? t("unpublish") : t("publish"),
            icon: app.published ? (
              <ArrowDownToLine aria-hidden="true" />
            ) : (
              <ArrowUpToLine aria-hidden="true" />
            ),
            onClick: () => setShowPublish(true)
          }
        ]
      : []),
    ...(permissions.includes("delete")
      ? [
          {
            label: t("delete"),
            icon: <Trash2 aria-hidden="true" />,
            variant: "destructive" as const,
            onClick: () => setShowDelete(true)
          }
        ]
      : [])
  ];

  return (
    <>
      <MoreMenu
        label={t("space_more_actions_for", { name: app.name })}
        alignment="end"
        items={items}
      />
      <PublishDialog
        open={showPublish}
        onOpenChange={setShowPublish}
        name={app.name}
        published={app.published}
        pending={publish.isPending}
        onConfirm={() => publish.mutate()}
      />
      <ConfirmDialogControlled
        open={showDelete}
        onOpenChange={setShowDelete}
        title={t("delete_app")}
        description={t("confirm_delete_app")}
        confirmLabel={deleteApp.isPending ? t("deleting") : t("delete")}
        pending={deleteApp.isPending}
        onConfirm={() => deleteApp.mutate()}
      />
    </>
  );
}
