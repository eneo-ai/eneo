import type { DropdownMenuOption } from "@astryxdesign/core/DropdownMenu";
import { MoreMenu } from "@astryxdesign/core/MoreMenu";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowDownToLine, ArrowUpToLine, Pencil, Trash2 } from "lucide-react";
import { useRouter } from "@/lib/navigation";
import { useTranslations } from "use-intl";
import type { ReactNode, RefObject } from "react";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { createResourceActions } from "@/components/composites/resource-action-scope";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { useRemovalMutation } from "@/features/spaces/removal";
import { useSpace } from "@/features/spaces/use-space";
import { PublishDialog } from "@/features/assistants/publish-dialog";
import type { AppSparse } from "./apps";
import { invalidateExpiringApiKeys } from "@/features/api-keys/api-keys";

type AppAction = "publish" | "delete";

const { ResourceActionScope, useOpenResourceAction } = createResourceActions<
  AppSparse,
  AppAction
>();

/** The publish and delete dialogs of an app's menu, held above the rows and cards that open them. */
function AppActionDialog({
  kind,
  resource: app,
  onClose
}: {
  kind: AppAction;
  resource: AppSparse;
  onClose: () => void;
}) {
  const t = useTranslations();
  const { routeId } = useSpace();
  const queryClient = useQueryClient();
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });

  const publish = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.POST("/api/v1/apps/{id}/publish/", {
          params: { path: { id: app.id }, query: { published: !app.published } }
        })
      ),
    onSuccess: () => {
      void invalidate();
      void invalidateExpiringApiKeys(queryClient);
      onClose();
    },
    onError: (error) => toastApiError(error, t)
  });

  const deleteApp = useRemovalMutation({
    mutationFn: () =>
      unwrap(browserApi.DELETE("/api/v1/apps/{id}/", { params: { path: { id: app.id } } })),
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
        name={app.name}
        published={app.published}
        pending={publish.isPending}
        onConfirm={() => publish.mutate()}
      />
    );
  }
  return (
    <ConfirmDialogControlled
      open
      onOpenChange={onOpenChange}
      title={t("delete_app")}
      description={t("confirm_delete_app")}
      confirmLabel={deleteApp.isPending ? t("deleting") : t("delete")}
      pending={deleteApp.isPending}
      onConfirm={() => deleteApp.mutate()}
    />
  );
}

/**
 * Above a collection of apps: what their menus open. A turn across 768 px
 * replaces the rows with cards and the open dialog stays. `focusTarget` is
 * where focus goes when the control that opened one is gone.
 */
export function AppActionScope({
  focusTarget,
  children
}: {
  focusTarget: RefObject<HTMLElement | null>;
  children: ReactNode;
}) {
  return (
    <ResourceActionScope Dialog={AppActionDialog} focusTarget={focusTarget}>
      {children}
    </ResourceActionScope>
  );
}

/** Edit/publish/delete menu for an app, shown on its tile. */
export function AppActions({ app }: { app: AppSparse }) {
  const t = useTranslations();
  const router = useRouter();
  const { routeId } = useSpace();
  const open = useOpenResourceAction();
  const permissions = app.permissions ?? [];

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
            onClick: () => open("publish", app)
          }
        ]
      : []),
    ...(permissions.includes("delete")
      ? [
          {
            label: t("delete"),
            icon: <Trash2 aria-hidden="true" />,
            variant: "destructive" as const,
            onClick: () => open("delete", app)
          }
        ]
      : [])
  ];

  return (
    <MoreMenu
      label={t("space_more_actions_for", { name: app.name })}
      alignment="end"
      items={items}
    />
  );
}
