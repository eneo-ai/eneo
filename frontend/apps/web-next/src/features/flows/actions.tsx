import { AlertDialog } from "@astryxdesign/core/AlertDialog";
import type { DropdownMenuOption } from "@astryxdesign/core/DropdownMenu";
import { MoreMenu } from "@astryxdesign/core/MoreMenu";
import { useMediaQuery } from "@astryxdesign/core/hooks";
import { useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useTranslations } from "use-intl";
import type { ReactNode, RefObject } from "react";
import { createResourceActions } from "@/components/composites/resource-action-scope";
import { toastApiError } from "@/lib/api/toast";
import { HANDHELD_QUERY } from "@/lib/hooks/use-media-match";
import { toast } from "@/lib/toast";
import { useRemovalMutation } from "@/features/spaces/removal";
import { useSpace } from "@/features/spaces/use-space";
import { deleteFlow, flowKeys, type FlowSparse } from "./flows-api";
import { evidenceExportAllowed } from "./flow-form-fields";
import { flowRefusalMessage } from "./flow-refusals";

type FlowAction = "delete";

const { ResourceActionScope, useOpenResourceAction } = createResourceActions<
  FlowSparse,
  FlowAction
>();

/** The delete dialog of a flow's menu, held above the rows, cards and table that open it. */
function FlowActionDialog({
  resource: flow,
  onClose
}: {
  resource: FlowSparse;
  onClose: () => void;
}) {
  const t = useTranslations();
  const { space } = useSpace();
  const queryClient = useQueryClient();

  const remove = useRemovalMutation({
    mutationFn: () => deleteFlow(flow.id),
    refresh: () => queryClient.invalidateQueries({ queryKey: flowKeys.list(space.id) }),
    onRemoved: () => {
      toast.success(t("flows_deleted", { name: flow.name }));
      onClose();
    },
    // A refusal (one the flags did not foresee, such as a 403) says why in words.
    onError: (error) => toastApiError(error, t, { message: flowRefusalMessage(error, [], t) })
  });

  return (
    <AlertDialog
      isOpen
      onOpenChange={(open) => {
        if (!open && !remove.isPending) onClose();
      }}
      title={t("flows_delete_title", { name: flow.name })}
      description={
        // A deleted flow can no longer be changed, so its runs' evidence
        // could then never be downloaded: say so before it is too late.
        evidenceExportAllowed(flow.metadata_json)
          ? t("flows_delete_description")
          : `${t("flows_delete_description")} ${t("flow_delete_evidence_export_off")}`
      }
      actionLabel={t("delete")}
      cancelLabel={t("cancel")}
      isActionLoading={remove.isPending}
      onAction={() => {
        if (!remove.isPending) remove.mutate();
      }}
    />
  );
}

/**
 * Above a collection of flows: what their menus open. A turn across 768 px
 * replaces the rows with cards and the open dialog stays. `focusTarget` is
 * where focus goes when the control that opened one is gone.
 */
export function FlowActionScope({
  focusTarget,
  children
}: {
  focusTarget: RefObject<HTMLElement | null>;
  children: ReactNode;
}) {
  return (
    <ResourceActionScope Dialog={FlowActionDialog} focusTarget={focusTarget}>
      {children}
    </ResourceActionScope>
  );
}

/**
 * The menu of a flow: delete, when the core lets the caller. A phone in a hand
 * runs and reviews flows and changes none, so there the menu is left out.
 */
export function FlowActions({ flow }: { flow: FlowSparse }) {
  const t = useTranslations();
  const open = useOpenResourceAction();
  const handheld = useMediaQuery(HANDHELD_QUERY);

  const items: DropdownMenuOption[] = [
    ...(flow.permissions.can_delete
      ? [
          {
            label: t("delete"),
            icon: <Trash2 aria-hidden="true" />,
            variant: "destructive" as const,
            onClick: () => open("delete", flow)
          }
        ]
      : [])
  ];
  if (handheld || items.length === 0) return null;

  return (
    <MoreMenu
      label={t("space_more_actions_for", { name: flow.name })}
      alignment="end"
      items={items}
    />
  );
}
