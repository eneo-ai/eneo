"use client";

import type { DropdownMenuOption } from "@astryxdesign/core/DropdownMenu";
import { MoreMenu } from "@astryxdesign/core/MoreMenu";
import { useQueryClient } from "@tanstack/react-query";
import { FolderInput, Pencil, Trash2 } from "lucide-react";
import { useRouter } from "@/lib/navigation";
import { useTranslations } from "use-intl";
import type { ReactNode, RefObject } from "react";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { createResourceActions } from "@/components/composites/resource-action-scope";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { MoveResourceDialog } from "@/features/knowledge/move-dialog";
import { useRemovalMutation } from "@/features/spaces/removal";
import { useSpace } from "@/features/spaces/use-space";
import type { ServiceSparse } from "./services";

type ServiceAction = "move" | "delete";

const { ResourceActionScope, useOpenResourceAction } = createResourceActions<
  ServiceSparse,
  ServiceAction
>();

/** The move and delete dialogs of a service's menu, held above the rows and cards that open them. */
function ServiceActionDialog({
  kind,
  resource: service,
  onClose
}: {
  kind: ServiceAction;
  resource: ServiceSparse;
  onClose: () => void;
}) {
  const t = useTranslations();
  const { routeId } = useSpace();
  const queryClient = useQueryClient();
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });

  const move = useRemovalMutation({
    mutationFn: (targetSpaceId: string) =>
      unwrap(
        browserApi.POST("/api/v1/services/{id}/transfer/", {
          params: { path: { id: service.id } },
          body: { target_space_id: targetSpaceId }
        })
      ),
    refresh: invalidate,
    onRemoved: onClose
  });

  const deleteService = useRemovalMutation({
    mutationFn: () =>
      unwrap(browserApi.DELETE("/api/v1/services/{id}/", { params: { path: { id: service.id } } })),
    refresh: invalidate,
    onRemoved: onClose
  });

  const onOpenChange = (open: boolean) => {
    if (!open) onClose();
  };

  if (kind === "move") {
    return (
      <MoveResourceDialog
        open
        onOpenChange={onOpenChange}
        title={t("move_service")}
        confirmLabel={t("move_service")}
        pending={move.isPending}
        onMove={(targetSpaceId) => move.mutate(targetSpaceId)}
      />
    );
  }
  return (
    <ConfirmDialogControlled
      open
      onOpenChange={onOpenChange}
      title={t("delete_service")}
      description={t("confirm_delete_service", { serviceName: service.name })}
      confirmLabel={deleteService.isPending ? t("deleting") : t("delete")}
      pending={deleteService.isPending}
      onConfirm={() => deleteService.mutate()}
    />
  );
}

/**
 * Above a collection of services: what their menus open. A turn across
 * 768 px replaces the rows with cards and the open dialog stays.
 * `focusTarget` is where focus goes when the control that opened one is gone.
 */
export function ServiceActionScope({
  focusTarget,
  children
}: {
  focusTarget: RefObject<HTMLElement | null>;
  children: ReactNode;
}) {
  return (
    <ResourceActionScope Dialog={ServiceActionDialog} focusTarget={focusTarget}>
      {children}
    </ResourceActionScope>
  );
}

/** Edit/move/delete menu for a service. Services have no publish. */
export function ServiceActions({ service }: { service: ServiceSparse }) {
  const t = useTranslations();
  const router = useRouter();
  const { routeId } = useSpace();
  const open = useOpenResourceAction();
  const permissions = service.permissions ?? [];

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
            onClick: () => open("move", service)
          },
          {
            label: t("delete"),
            icon: <Trash2 aria-hidden="true" />,
            variant: "destructive" as const,
            onClick: () => open("delete", service)
          }
        ]
      : [])
  ];

  return (
    <MoreMenu
      label={t("space_more_actions_for", { name: service.name })}
      alignment="end"
      items={items}
    />
  );
}
