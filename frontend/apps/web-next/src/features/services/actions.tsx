"use client";

import type { DropdownMenuOption } from "@astryxdesign/core/DropdownMenu";
import { MoreMenu } from "@astryxdesign/core/MoreMenu";
import { useQueryClient } from "@tanstack/react-query";
import { FolderInput, Pencil, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { MoveResourceDialog } from "@/features/knowledge/move-dialog";
import { useRemovalMutation } from "@/features/spaces/removal";
import { useSpace } from "@/features/spaces/use-space";
import type { ServiceSparse } from "./services";

/** Edit/move/delete menu for a service. Services have no publish or knowledge transfer. */
export function ServiceActions({ service }: { service: ServiceSparse }) {
  const t = useTranslations();
  const router = useRouter();
  const { routeId } = useSpace();
  const queryClient = useQueryClient();
  const [showMove, setShowMove] = useState(false);
  const [showDelete, setShowDelete] = useState(false);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });
  const permissions = service.permissions ?? [];

  const move = useRemovalMutation({
    mutationFn: (targetSpaceId: string) =>
      unwrap(
        browserApi.POST("/api/v1/services/{id}/transfer/", {
          params: { path: { id: service.id } },
          body: { target_space_id: targetSpaceId, move_resources: false }
        })
      ),
    refresh: invalidate,
    onRemoved: () => setShowMove(false)
  });

  const deleteService = useRemovalMutation({
    mutationFn: () =>
      unwrap(browserApi.DELETE("/api/v1/services/{id}/", { params: { path: { id: service.id } } })),
    refresh: invalidate,
    onRemoved: () => setShowDelete(false)
  });

  if (!permissions.some((permission) => ["edit", "delete"].includes(permission))) {
    return null;
  }

  const items: DropdownMenuOption[] = [
    ...(permissions.includes("edit")
      ? [
          {
            label: t("edit"),
            icon: <Pencil aria-hidden="true" />,
            onClick: () => router.push(`/spaces/${routeId}/services/${service.id}?tab=settings`)
          }
        ]
      : []),
    ...(permissions.includes("delete")
      ? [
          {
            label: t("move"),
            icon: <FolderInput aria-hidden="true" />,
            onClick: () => setShowMove(true)
          },
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
        label={t("space_more_actions_for", { name: service.name })}
        alignment="end"
        items={items}
      />
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
