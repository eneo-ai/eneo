"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "use-intl";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import type { SecurityClassification } from "@/features/admin/security-classifications/security-classifications";
import { useRemovalMutation } from "@/features/spaces/removal";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError, getErrorMessage } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { toast } from "@/lib/toast";
import { modelDisplayName } from "@/lib/models/model-display-name";
import { DeleteBlockedDialog } from "./delete-blocked-dialog";
import { EditModelDialog } from "./edit-model-dialog";
import { MigrateModelDialog } from "./migrate-model-dialog";
import { ModelDetailDialog } from "./model-detail-dialog";
import { deleteTenantModel, imageModelUsedBy, MODELS_KEY } from "./models";
import type { KindedModel } from "./provider-sections";

export type ModelAction = "edit" | "migrate" | "detail" | "delete";
export type ModelSelection = KindedModel & { action: ModelAction };

/** The provider owns the active dialog across row/table layout changes. */
export function ModelDialogs({
  selection,
  classifications,
  securityEnabled,
  onClose,
  onMigrate
}: {
  selection: ModelSelection;
  classifications: SecurityClassification[];
  securityEnabled: boolean;
  onClose: () => void;
  onMigrate: () => void;
}) {
  const { model, kind, action } = selection;
  const t = useTranslations();
  const queryClient = useQueryClient();
  const refetchModels = () => queryClient.invalidateQueries({ queryKey: MODELS_KEY });
  const onOpenChange = (open: boolean) => {
    if (!open) onClose();
  };
  const label = modelDisplayName(model);
  const usedBy = imageModelUsedBy(model);
  const deleteBlocked = usedBy.length > 0;
  const usedByNames = usedBy.map((source) => source.name).join(", ");
  const remove = useRemovalMutation({
    mutationFn: () => deleteTenantModel(browserApi, kind, model.id),
    refresh: refetchModels,
    onRemoved: () => {
      onClose();
      toast.success(t("model_deleted_success"));
    },
    onError: (error) => {
      if (
        error instanceof EneoApiError &&
        error.code === 9039 &&
        (kind === "completion" || kind === "transcription")
      ) {
        toast.error(getErrorMessage(error, t), {
          action: {
            label: t("migrate"),
            onClick: () => {
              onMigrate();
            }
          }
        });
        return;
      }
      toastApiError(error, t);
    }
  });

  return (
    <>
      {action === "edit" && (
        <EditModelDialog
          model={model}
          kind={kind}
          classifications={classifications}
          securityEnabled={securityEnabled}
          open
          onOpenChange={onOpenChange}
        />
      )}
      {action === "migrate" && (kind === "completion" || kind === "transcription") && (
        <MigrateModelDialog model={model} kind={kind} open onOpenChange={onOpenChange} />
      )}
      {action === "detail" && kind !== "embedding" && (
        <ModelDetailDialog model={model} kind={kind} open onOpenChange={onOpenChange} />
      )}
      {action === "delete" && deleteBlocked && (
        <DeleteBlockedDialog
          open
          onOpenChange={onOpenChange}
          title={t("admin_models_delete_blocked_title", { name: label })}
          description={t("admin_models_delete_blocked_description", { names: usedByNames })}
        />
      )}
      {action === "delete" && !deleteBlocked && (
        <ConfirmDialogControlled
          open
          onOpenChange={onOpenChange}
          title={t("delete_model")}
          description={`${t("delete_model_confirm", { name: label })} ${t("delete_model_warning")}`}
          confirmLabel={remove.isPending ? t("deleting") : t("delete")}
          pending={remove.isPending}
          onConfirm={() => remove.mutate()}
        />
      )}
    </>
  );
}
