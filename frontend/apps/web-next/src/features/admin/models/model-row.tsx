"use client";

import { Badge } from "@astryxdesign/core/Badge";
import {
  DropdownMenu,
  DropdownMenuDivider,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSubMenu
} from "@astryxdesign/core/DropdownMenu";
import { Switch } from "@astryxdesign/core/Switch";
import { TableCell, TableRow } from "@astryxdesign/core/Table";
import { Text } from "@astryxdesign/core/Text";
import { Token } from "@astryxdesign/core/Token";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeftRight,
  Info,
  MoreHorizontal,
  Pencil,
  ShieldCheck,
  Star,
  Trash2
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import type { SecurityClassification } from "@/features/admin/security-classifications/security-classifications";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError, getErrorMessage, unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { toast } from "@/lib/toast";
import { cn } from "@/lib/utils";
import { EditModelDialog } from "./edit-model-dialog";
import { MigrateModelDialog } from "./migrate-model-dialog";
import { useModelTypeLabel } from "./model-type-label";
import { ModelDetailDialog } from "./model-detail-dialog";
import {
  type AdminModel,
  deleteTenantModel,
  type MigratableModelKind,
  MODELS_KEY,
  modelLabel,
  type ModelKind
} from "./models";
import { modelLifecycle, modelPrice } from "./provider-sections";

type ModelFlags = {
  is_org_enabled?: boolean | null;
  is_org_default?: boolean | null;
  security_classification?: { id: string } | null;
};

/** Radio value for "no classification" in the row menu. */
const NO_CLASSIFICATION = "__none__";

async function updateModelFlags(kind: ModelKind, id: string, flags: ModelFlags): Promise<void> {
  if (kind === "completion") {
    await unwrap(
      browserApi.POST("/api/v1/completion-models/{id}/", { params: { path: { id } }, body: flags })
    );
  } else if (kind === "transcription") {
    await unwrap(
      browserApi.POST("/api/v1/transcription-models/{id}/", {
        params: { path: { id } },
        body: flags
      })
    );
  } else {
    await unwrap(
      browserApi.POST("/api/v1/embedding-models/{id}/", {
        params: { path: { id } },
        // Omitted means "keep"; null removes the classification ("Ingen").
        body: {
          is_org_enabled: flags.is_org_enabled ?? undefined,
          security_classification: flags.security_classification
        }
      })
    );
  }
}

function hasDefault(model: AdminModel): model is AdminModel & { is_org_default?: boolean } {
  return "is_org_default" in model;
}

/** Vision / reasoning / tools as small tokens; "–" where the type has none. */
function Capabilities({ model }: { model: AdminModel }) {
  const t = useTranslations();
  const labels = [
    "vision" in model && model.vision ? t("admin_models_capability_vision") : null,
    "reasoning" in model && model.reasoning ? t("model_label_reasoning") : null,
    "supports_tool_calling" in model && model.supports_tool_calling
      ? t("model_label_tool_calling")
      : null
  ].filter((label): label is string => label !== null);

  if (labels.length === 0) {
    return (
      <>
        <span aria-hidden="true" className="text-ax-text-secondary">
          –
        </span>
        <span className="sr-only">{t("none")}</span>
      </>
    );
  }
  return (
    <ul className="flex flex-wrap gap-1">
      {labels.map((label) => (
        <li key={label} className="flex">
          <Token label={label} size="sm" />
        </li>
      ))}
    </ul>
  );
}

/** Mono price, right-aligned by the cell; screen readers get "Indata $5, utdata $25". */
function Price({ model, kind }: { model: AdminModel; kind: ModelKind }) {
  const t = useTranslations();
  const price = modelPrice(model, kind);

  if (price.kind === "unknown") {
    return (
      <>
        <span aria-hidden="true" className="text-ax-text-secondary">
          –
        </span>
        <span className="sr-only">{t("model_cost_unknown")}</span>
      </>
    );
  }
  if (price.kind === "minute") {
    return (
      <span className="font-mono text-xs tabular-nums">
        {t("model_cost_per_minute", { cost: price.value })}
      </span>
    );
  }
  // Embeddings usually have no output price; collapse to one value unless they differ.
  if (price.input && price.output && price.input !== price.output) {
    return (
      <>
        <span aria-hidden="true" className="font-mono text-xs whitespace-nowrap tabular-nums">
          {price.input} / {price.output}
        </span>
        <span className="sr-only">
          {t("admin_models_price_in_out", { input: price.input, output: price.output })}
        </span>
      </>
    );
  }
  return <span className="font-mono text-xs tabular-nums">{price.input ?? price.output}</span>;
}

export function ModelRow({
  model,
  kind,
  classifications,
  securityEnabled,
  showKind = false,
  onRemoved
}: {
  model: AdminModel;
  kind: ModelKind;
  classifications: SecurityClassification[];
  securityEnabled: boolean;
  showKind?: boolean;
  /** Called after the model was deleted and the list refetched. */
  onRemoved?: () => void;
}) {
  const t = useTranslations();
  const typeLabel = useModelTypeLabel();
  const queryClient = useQueryClient();
  const [showEdit, setShowEdit] = useState(false);
  const [showMigrate, setShowMigrate] = useState(false);
  const [showDetail, setShowDetail] = useState(false);
  const [showDelete, setShowDelete] = useState(false);
  const canViewDetail = kind === "completion" || kind === "transcription";

  const label = modelLabel(model);
  // Each returns the refetch, so a mutation stays pending until the list has
  // the new state. One mutation per control, so a pending write on one never
  // resets another's optimistic state.
  const refetchModels = () => queryClient.invalidateQueries({ queryKey: MODELS_KEY });
  const enable = useMutation({
    mutationFn: (next: boolean) => updateModelFlags(kind, model.id, { is_org_enabled: next }),
    // Presses during a write queue behind it instead of being dropped.
    scope: { id: `model-enabled:${kind}:${model.id}` },
    onSuccess: refetchModels,
    onError: (error) => toastApiError(error, t)
  });
  const makeDefault = useMutation({
    mutationFn: () => updateModelFlags(kind, model.id, { is_org_default: true }),
    onSuccess: () => {
      toast.success(t("admin_models_default_set", { name: label }));
      return refetchModels();
    },
    onError: (error) => toastApiError(error, t)
  });
  const classify = useMutation({
    mutationFn: (classification: SecurityClassification | null) =>
      updateModelFlags(kind, model.id, {
        security_classification: classification && { id: classification.id }
      }),
    onSuccess: (_data, classification) => {
      toast.success(
        classification
          ? t("admin_models_classification_set", {
              name: label,
              classification: classification.name
            })
          : t("admin_models_classification_removed", { name: label })
      );
      return refetchModels();
    },
    onError: (error) => toastApiError(error, t)
  });

  // The technical id under the display name, unless the name already is the id.
  const technicalId = model.name !== label ? model.name : null;
  const locked = model.is_locked ?? false;
  const readonly = "readonly" in model && model.readonly === true;
  const isDefault = hasDefault(model) && model.is_org_default === true;
  const currentClassification =
    (model as { security_classification?: SecurityClassification | null })
      .security_classification ?? null;
  const supportsDefault = kind !== "embedding";
  const supportsClassification = securityEnabled;
  const canEdit = !readonly;
  const canMigrate =
    (kind === "completion" || kind === "transcription") &&
    !("migrated_to_model_id" in model && model.migrated_to_model_id);
  const canDelete = !readonly;
  const lifecycle = modelLifecycle(model);
  // Menu groups: open/change the model · org-wide flags · delete.
  const hasModelActions = canViewDetail || canEdit || canMigrate;
  const hasFlagActions = supportsDefault || supportsClassification;
  const hasMenu = hasModelActions || hasFlagActions || canDelete;

  // Shows the latest press while writes and the refetch are in flight;
  // falls back to the saved state when the last write failed.
  const enabled = enable.isPending ? enable.variables : (model.is_org_enabled ?? false);

  const remove = useMutation({
    mutationFn: () => deleteTenantModel(browserApi, kind, model.id),
    onSuccess: async () => {
      setShowDelete(false);
      toast.success(t("model_deleted_success"));
      await queryClient.invalidateQueries({ queryKey: MODELS_KEY });
      onRemoved?.();
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
              setShowDelete(false);
              setShowMigrate(true);
            }
          }
        });
        return;
      }
      toastApiError(error, t);
    }
  });

  return (
    <TableRow>
      <TableCell>
        <Switch
          label={t("admin_models_enable_model", { name: label })}
          isLabelHidden
          value={enabled}
          onChange={(next) => enable.mutate(next)}
          isDisabled={locked}
          disabledMessage={locked ? t("api_credentials_required_for_provider") : undefined}
        />
      </TableCell>

      <TableCell>
        <div className="flex min-w-0 flex-col gap-0.5">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            {canViewDetail ? (
              <button
                type="button"
                aria-haspopup="dialog"
                onClick={() => setShowDetail(true)}
                className={cn(
                  "focus-visible:outline-ring rounded-ax-inner inline-flex min-h-6 items-center text-start font-semibold break-words hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:min-h-11",
                  enabled ? "text-ax-text" : "text-ax-text-secondary"
                )}
              >
                {label}
              </button>
            ) : (
              <span
                className={cn(
                  "font-semibold break-words",
                  enabled ? "text-ax-text" : "text-ax-text-secondary"
                )}
              >
                {label}
              </span>
            )}
            {isDefault && <Badge variant="blue" label={t("admin_models_default_badge")} />}
            {lifecycle.kind === "deprecated" && (
              <Badge variant="error" label={t("model_label_deprecated")} />
            )}
            {lifecycle.kind === "retiring" && (
              <Badge
                variant="warning"
                label={t("model_label_retiring", { date: lifecycle.date })}
              />
            )}
          </div>
          {technicalId && (
            <Text type="code" size="sm" color="secondary" maxLines={1}>
              {technicalId}
            </Text>
          )}
        </div>
      </TableCell>

      {showKind && (
        <TableCell>
          <span className="text-ax-text-secondary">{typeLabel(kind)}</span>
        </TableCell>
      )}

      <TableCell>
        <Capabilities model={model} />
      </TableCell>

      {/* Inactive rows are dimmed with the secondary text token, never opacity. */}
      <TableCell className={cn("text-end", !enabled && "text-ax-text-secondary")}>
        <Price model={model} kind={kind} />
      </TableCell>

      {securityEnabled && (
        <TableCell>
          {currentClassification ? (
            <Badge label={currentClassification.name} />
          ) : (
            <span className="text-ax-text-secondary text-sm">{t("admin_models_unclassified")}</span>
          )}
        </TableCell>
      )}

      <TableCell className="text-end">
        {hasMenu && (
          <DropdownMenu
            button={{
              label: t("admin_models_row_menu", { name: label }),
              tooltip: t("admin_models_row_menu", { name: label }),
              icon: <MoreHorizontal className="size-4" aria-hidden="true" />,
              isIconOnly: true,
              variant: "ghost",
              size: "sm"
            }}
            hasChevron={false}
            alignment="end"
          >
            {canViewDetail && (
              <DropdownMenuItem
                icon={Info}
                label={t("model_details")}
                onClick={() => setShowDetail(true)}
              />
            )}
            {canEdit && (
              <DropdownMenuItem icon={Pencil} label={t("edit")} onClick={() => setShowEdit(true)} />
            )}
            {canMigrate && (
              <DropdownMenuItem
                icon={ArrowLeftRight}
                label={t("migrate")}
                onClick={() => setShowMigrate(true)}
              />
            )}
            {hasModelActions && hasFlagActions && <DropdownMenuDivider />}
            {supportsDefault && (
              <DropdownMenuItem
                icon={Star}
                label={t("set_as_default_model")}
                isDisabled={isDefault || !enabled || makeDefault.isPending}
                onClick={() => makeDefault.mutate()}
              />
            )}
            {supportsClassification && (
              <DropdownMenuSubMenu icon={ShieldCheck} label={t("security_classification")}>
                <DropdownMenuRadioGroup
                  label={t("security_classification")}
                  value={currentClassification?.id ?? NO_CLASSIFICATION}
                  onChange={(value) =>
                    classify.mutate(
                      classifications.find((classification) => classification.id === value) ?? null
                    )
                  }
                >
                  <DropdownMenuRadioItem value={NO_CLASSIFICATION} label={t("none")} />
                  {classifications.map((classification) => (
                    <DropdownMenuRadioItem
                      key={classification.id}
                      value={classification.id}
                      label={classification.name}
                    />
                  ))}
                </DropdownMenuRadioGroup>
              </DropdownMenuSubMenu>
            )}
            {canDelete && (hasModelActions || hasFlagActions) && <DropdownMenuDivider />}
            {canDelete && (
              <DropdownMenuItem
                icon={Trash2}
                label={t("delete")}
                variant="destructive"
                onClick={() => setShowDelete(true)}
              />
            )}
          </DropdownMenu>
        )}

        {canEdit && (
          <EditModelDialog
            model={model}
            kind={kind}
            classifications={classifications}
            securityEnabled={securityEnabled}
            open={showEdit}
            onOpenChange={setShowEdit}
          />
        )}
        {canMigrate && (
          <MigrateModelDialog
            model={model}
            kind={kind as MigratableModelKind}
            open={showMigrate}
            onOpenChange={setShowMigrate}
          />
        )}
        {canViewDetail && (
          <ModelDetailDialog
            model={model}
            kind={kind as "completion" | "transcription"}
            open={showDetail}
            onOpenChange={setShowDetail}
          />
        )}
        {canDelete && (
          <ConfirmDialogControlled
            open={showDelete}
            onOpenChange={setShowDelete}
            title={t("delete_model")}
            description={`${t("delete_model_confirm", { name: label })} ${t("delete_model_warning")}`}
            confirmLabel={remove.isPending ? t("deleting") : t("delete")}
            pending={remove.isPending}
            onConfirm={() => remove.mutate()}
          />
        )}
      </TableCell>
    </TableRow>
  );
}
