"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FolderInput, MoreHorizontal, Pencil, Trash2 } from "lucide-react";
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
import { MoveResourceDialog } from "@/features/knowledge/move-dialog";
import { useSpace } from "@/features/spaces/use-space";
import type { ServiceSparse } from "./services";

/** Edit/move/delete menu for a service. Services have no publish or knowledge transfer. */
export function ServiceActions({ service }: { service: ServiceSparse }) {
  const t = useTranslations();
  const { routeId } = useSpace();
  const queryClient = useQueryClient();
  const [showMove, setShowMove] = useState(false);
  const [showDelete, setShowDelete] = useState(false);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });
  const permissions = service.permissions ?? [];

  const move = useMutation({
    mutationFn: (targetSpaceId: string) =>
      unwrap(
        browserApi.POST("/api/v1/services/{id}/transfer/", {
          params: { path: { id: service.id } },
          body: { target_space_id: targetSpaceId, move_resources: false }
        })
      ),
    onSuccess: () => {
      invalidate();
      setShowMove(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  const deleteService = useMutation({
    mutationFn: () =>
      unwrap(browserApi.DELETE("/api/v1/services/{id}/", { params: { path: { id: service.id } } })),
    onSuccess: () => {
      invalidate();
      setShowDelete(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  if (!permissions.some((permission) => ["edit", "delete"].includes(permission))) {
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
              <Link href={`/spaces/${routeId}/services/${service.id}?tab=settings`}>
                <Pencil className="size-4" /> {t("edit")}
              </Link>
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
      <MoveResourceDialog
        open={showMove}
        onOpenChange={setShowMove}
        title={t("move_service")}
        confirmLabel={t("move_service")}
        pending={move.isPending}
        onMove={(targetSpaceId) => move.mutate(targetSpaceId)}
      />
      <ConfirmDialogControlled
        open={showDelete}
        onOpenChange={setShowDelete}
        title={t("delete_service")}
        description={t("confirm_delete_service", { serviceName: service.name })}
        confirmLabel={deleteService.isPending ? t("deleting") : t("delete")}
        pending={deleteService.isPending}
        onConfirm={() => deleteService.mutate()}
      />
    </>
  );
}
