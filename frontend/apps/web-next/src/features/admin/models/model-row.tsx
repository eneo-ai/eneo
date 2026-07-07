"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeftRight,
  Brain,
  Check,
  Clock,
  Eye,
  MoreHorizontal,
  Pencil,
  Star,
  TriangleAlert,
  Trash2,
  Wrench
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { Switch } from "@/components/ui/switch";
import { TableCell, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  formatCostPerMillionTokens,
  formatCostPerMinute,
  getDeprecationStatus
} from "@/features/ai-models/format-model-stats";
import type { SecurityClassification } from "@/features/admin/security-classifications/security-classifications";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError, getErrorMessage, unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { cn } from "@/lib/utils";
import { EditModelDialog } from "./edit-model-dialog";
import { MigrateModelDialog } from "./migrate-model-dialog";
import { ModelDetailDialog } from "./model-detail-dialog";
import {
  type AdminModel,
  deleteTenantModel,
  type MigratableModelKind,
  MODELS_KEY,
  modelLabel,
  type ModelKind
} from "./models";

type ModelFlags = {
  is_org_enabled?: boolean | null;
  is_org_default?: boolean | null;
  security_classification?: { id: string } | null;
};

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
        body: {
          is_org_enabled: flags.is_org_enabled ?? undefined,
          security_classification: flags.security_classification ?? undefined
        }
      })
    );
  }
}

function hasDefault(model: AdminModel): model is AdminModel & { is_org_default?: boolean } {
  return "is_org_default" in model;
}
function hasClassification(model: AdminModel): boolean {
  return "security_classification" in model;
}

/**
 * Indicative price chip — per 1M tokens (completion / embedding) or per audio
 * minute (transcription). Shows "–" with a tooltip when unpriced so admins spot
 * models without a cost on record. Mirrors the Svelte `ModelCostBadge`.
 */
function ModelCostChip({ model, kind }: { model: AdminModel; kind: ModelKind }) {
  const t = useTranslations();

  let text: string;
  let hasData: boolean;
  let tooltip: string;

  if (kind === "transcription") {
    const value = formatCostPerMinute(
      (model as { cost_per_minute?: string | null }).cost_per_minute
    );
    hasData = value !== null;
    text = value ? t("model_cost_per_minute", { cost: value }) : "–";
    tooltip = hasData ? t("model_cost_tooltip_per_minute") : t("model_cost_unknown");
  } else {
    const m = model as {
      input_cost_per_token?: string | null;
      output_cost_per_token?: string | null;
    };
    const input = formatCostPerMillionTokens(m.input_cost_per_token);
    const output = formatCostPerMillionTokens(m.output_cost_per_token);
    hasData = input !== null || output !== null;
    // Embeddings usually have no output price; collapse to one value unless they differ.
    if (!input && !output) text = "–";
    else if (input && output && input !== output) text = `${input} / ${output}`;
    else text = input ?? output ?? "–";
    tooltip = hasData ? t("model_cost_tooltip_per_million") : t("model_cost_unknown");
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className="bg-muted text-muted-foreground inline-flex items-center rounded-md border px-1.5 py-0.5 font-mono text-[11px] tabular-nums"
          aria-label={`${tooltip}: ${text}`}
        >
          {text}
        </span>
      </TooltipTrigger>
      <TooltipContent>{tooltip}</TooltipContent>
    </Tooltip>
  );
}

/**
 * Compact capability + lifecycle icons (vision / reasoning / tools, plus a
 * deprecation or retirement warning) with tooltips, followed by an indicative
 * cost chip — the dense badge text is replaced by glyphs so the table scans at
 * a glance, matching the Svelte admin.
 */
function ModelStatusIcons({ model, kind }: { model: AdminModel; kind: ModelKind }) {
  const t = useTranslations();
  const dep = getDeprecationStatus(model);

  const icons: {
    key: string;
    Icon: typeof Eye;
    className: string;
    label: string;
    tooltip: string;
  }[] = [];

  if (dep.kind === "deprecated") {
    icons.push({
      key: "deprecated",
      Icon: TriangleAlert,
      className: "text-destructive",
      label: t("model_label_deprecated"),
      tooltip: t("model_tooltip_deprecated", { date: dep.date ?? "" })
    });
  } else if (dep.kind === "retiring") {
    icons.push({
      key: "retiring",
      Icon: Clock,
      className: "text-warning",
      label: t("model_label_retiring", { date: dep.date ?? "" }),
      tooltip: t("model_tooltip_retiring", { date: dep.date ?? "" })
    });
  }
  if ("reasoning" in model && model.reasoning) {
    icons.push({
      key: "reasoning",
      Icon: Brain,
      className: "text-muted-foreground",
      label: t("model_label_reasoning"),
      tooltip: t("model_tooltip_reasoning")
    });
  }
  if ("vision" in model && model.vision) {
    icons.push({
      key: "vision",
      Icon: Eye,
      className: "text-muted-foreground",
      label: t("model_label_vision"),
      tooltip: t("model_tooltip_vision")
    });
  }
  if ("supports_tool_calling" in model && model.supports_tool_calling) {
    icons.push({
      key: "tools",
      Icon: Wrench,
      className: "text-muted-foreground",
      label: t("model_label_tool_calling"),
      tooltip: t("model_tooltip_tool_calling")
    });
  }

  return (
    <span className="flex items-center gap-2">
      {icons.length > 0 && (
        <span
          role="list"
          aria-label={t("model_capabilities_label")}
          className="flex items-center gap-2"
        >
          {icons.map(({ key, Icon, className, label, tooltip }) => (
            <Tooltip key={key}>
              <TooltipTrigger asChild>
                <span role="listitem" aria-label={label} className={cn("inline-flex", className)}>
                  <Icon className="size-4" aria-hidden="true" />
                </span>
              </TooltipTrigger>
              <TooltipContent>{tooltip}</TooltipContent>
            </Tooltip>
          ))}
        </span>
      )}
      <ModelCostChip model={model} kind={kind} />
    </span>
  );
}

export function ModelRow({
  model,
  kind,
  classifications,
  securityEnabled,
  showKind = false
}: {
  model: AdminModel;
  kind: ModelKind;
  classifications: SecurityClassification[];
  securityEnabled: boolean;
  showKind?: boolean;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [showEdit, setShowEdit] = useState(false);
  const [showMigrate, setShowMigrate] = useState(false);
  const [showDetail, setShowDetail] = useState(false);
  const [showDelete, setShowDelete] = useState(false);
  const canViewDetail = kind === "completion" || kind === "transcription";

  const flags = useMutation({
    mutationFn: (next: ModelFlags) => updateModelFlags(kind, model.id, next),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: MODELS_KEY }),
    onError: (error) => toastApiError(error, t)
  });

  const locked = model.is_locked ?? false;
  const readonly = "readonly" in model && model.readonly === true;
  const isDefault = hasDefault(model) && model.is_org_default;
  const currentClassification = hasClassification(model)
    ? ((model as { security_classification?: SecurityClassification | null })
        .security_classification ?? null)
    : null;
  const supportsDefault = kind !== "embedding";
  const supportsClassification = securityEnabled;
  const canEdit = !readonly;
  const canMigrate =
    (kind === "completion" || kind === "transcription") &&
    !("migrated_to_model_id" in model && model.migrated_to_model_id);
  const canDelete = !readonly;
  const showActions =
    supportsDefault || supportsClassification || canEdit || canMigrate || canDelete;
  const dep = getDeprecationStatus(model);

  const remove = useMutation({
    mutationFn: () => deleteTenantModel(browserApi, kind, model.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: MODELS_KEY });
      toast.success(t("model_deleted_success"));
      setShowDelete(false);
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
    <TableRow
      className={cn(
        dep.kind === "deprecated" && "bg-destructive/5",
        dep.kind === "retiring" && "bg-warning/5"
      )}
    >
      <TableCell>
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="inline-flex">
              <Switch
                checked={model.is_org_enabled ?? false}
                disabled={locked || flags.isPending}
                aria-label={modelLabel(model)}
                onCheckedChange={(checked) => flags.mutate({ is_org_enabled: checked })}
              />
            </span>
          </TooltipTrigger>
          <TooltipContent>
            {locked
              ? t("api_credentials_required_for_provider")
              : model.is_org_enabled
                ? t("toggle_to_disable_model")
                : t("toggle_to_enable_model")}
          </TooltipContent>
        </Tooltip>
      </TableCell>
      <TableCell className="font-medium">
        <span className="flex items-center gap-2">
          {canViewDetail ? (
            <button
              type="button"
              className="text-left hover:underline"
              onClick={() => setShowDetail(true)}
            >
              {modelLabel(model)}
            </button>
          ) : (
            modelLabel(model)
          )}
          {showKind && (
            <Badge variant="outline" className="capitalize">
              {t(`${kind}_models_singular`)}
            </Badge>
          )}
          {isDefault && (
            <Badge variant="secondary" className="gap-1">
              <Star className="size-3" /> {t("default_model")}
            </Badge>
          )}
        </span>
      </TableCell>
      <TableCell>
        <ModelStatusIcons model={model} kind={kind} />
      </TableCell>
      {securityEnabled && (
        <TableCell className="text-muted-foreground text-sm">
          {currentClassification?.name ?? "—"}
        </TableCell>
      )}
      <TableCell className="w-12">
        {showActions && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" aria-label={t("actions")}>
                <MoreHorizontal className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {canEdit && (
                <DropdownMenuItem onSelect={() => setShowEdit(true)}>
                  <Pencil className="size-4" /> {t("edit")}
                </DropdownMenuItem>
              )}
              {canMigrate && (
                <DropdownMenuItem onSelect={() => setShowMigrate(true)}>
                  <ArrowLeftRight className="size-4" /> {t("migrate")}
                </DropdownMenuItem>
              )}
              {canDelete && (
                <DropdownMenuItem variant="destructive" onSelect={() => setShowDelete(true)}>
                  <Trash2 className="size-4" /> {t("delete")}
                </DropdownMenuItem>
              )}
              {(canEdit || canMigrate || canDelete) &&
                (supportsDefault || supportsClassification) && <DropdownMenuSeparator />}
              {supportsDefault && (
                <DropdownMenuItem
                  disabled={isDefault || !model.is_org_enabled}
                  onSelect={() => flags.mutate({ is_org_default: true })}
                >
                  <Star className="size-4" /> {t("set_as_default_model")}
                </DropdownMenuItem>
              )}
              {supportsClassification && (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuLabel>{t("security_classification")}</DropdownMenuLabel>
                  <DropdownMenuItem
                    onSelect={() => flags.mutate({ security_classification: null })}
                  >
                    <Check
                      className={currentClassification ? "size-4 opacity-0" : "size-4 opacity-100"}
                    />
                    {t("none")}
                  </DropdownMenuItem>
                  {classifications.map((classification) => (
                    <DropdownMenuItem
                      key={classification.id}
                      onSelect={() =>
                        flags.mutate({ security_classification: { id: classification.id } })
                      }
                    >
                      <Check
                        className={
                          currentClassification?.id === classification.id
                            ? "size-4 opacity-100"
                            : "size-4 opacity-0"
                        }
                      />
                      {classification.name}
                    </DropdownMenuItem>
                  ))}
                </>
              )}
            </DropdownMenuContent>
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
            description={`${t("delete_model_confirm", { name: modelLabel(model) })} ${t("delete_model_warning")}`}
            confirmLabel={remove.isPending ? t("deleting") : t("delete")}
            pending={remove.isPending}
            onConfirm={() => remove.mutate()}
          />
        )}
      </TableCell>
    </TableRow>
  );
}
