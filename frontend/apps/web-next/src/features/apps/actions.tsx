"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowDownToLine, ArrowUpToLine, MoreHorizontal, Pencil, Trash2 } from "lucide-react";
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
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { useSpace } from "@/features/spaces/use-space";
import { PublishDialog } from "@/features/assistants/publish-dialog";
import type { AppSparse } from "./apps";

/** Edit/publish/delete menu for an app, shown on its tile. */
export function AppActions({ app }: { app: AppSparse }) {
  const t = useTranslations();
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
      invalidate();
      setShowPublish(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  const deleteApp = useMutation({
    mutationFn: () =>
      unwrap(browserApi.DELETE("/api/v1/apps/{id}/", { params: { path: { id: app.id } } })),
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
              <Link href={`/spaces/${routeId}/apps/${app.id}/edit`}>
                <Pencil className="size-4" /> {t("edit")}
              </Link>
            </DropdownMenuItem>
          )}
          {permissions.includes("publish") && (
            <DropdownMenuItem onSelect={() => setShowPublish(true)}>
              {app.published ? (
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
