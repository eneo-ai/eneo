"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeftRight, Check, MoreHorizontal, Pencil, Star } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Button } from "@/components/ui/button";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import type { SecurityClassification } from "@/features/admin/security-classifications/security-classifications";
import {
  groupByProvider,
  MODELS_KEY,
  modelLabel,
  type AdminModel,
  type CompletionModelAdmin,
  type ModelKind
} from "./models";
import { EditModelDialog } from "./edit-model-dialog";
import { MigrateModelDialog } from "./migrate-model-dialog";
import { ModelDetailDialog } from "./model-detail-dialog";

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
        body: { is_org_enabled: flags.is_org_enabled ?? undefined }
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

function ModelRow({
  model,
  kind,
  classifications,
  securityEnabled
}: {
  model: AdminModel;
  kind: ModelKind;
  classifications: SecurityClassification[];
  securityEnabled: boolean;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [showEdit, setShowEdit] = useState(false);
  const [showMigrate, setShowMigrate] = useState(false);
  const [showDetail, setShowDetail] = useState(false);
  const canViewDetail = kind === "completion" || kind === "transcription";

  const flags = useMutation({
    mutationFn: (next: ModelFlags) => updateModelFlags(kind, model.id, next),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: MODELS_KEY }),
    onError: (error) => toastApiError(error, t)
  });

  const locked = model.is_locked ?? false;
  const isDefault = hasDefault(model) && model.is_org_default;
  const currentClassification = hasClassification(model)
    ? ((model as { security_classification?: SecurityClassification | null })
        .security_classification ?? null)
    : null;
  const supportsDefault = kind !== "embedding";
  const supportsClassification = securityEnabled && kind !== "embedding";
  // Only tenant (custom) completion models carry an editable metadata contract.
  const canEdit = kind === "completion" && !("readonly" in model && model.readonly);
  // Migration moves a completion model's usage onto a replacement.
  const canMigrate =
    kind === "completion" && !("migrated_to_model_id" in model && model.migrated_to_model_id);
  const showActions = supportsDefault || supportsClassification || canEdit || canMigrate;

  return (
    <TableRow>
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
          {isDefault && (
            <Badge variant="secondary" className="gap-1">
              <Star className="size-3" /> {t("default_model")}
            </Badge>
          )}
        </span>
        {model.description && (
          <span className="text-muted-foreground line-clamp-1 text-xs">{model.description}</span>
        )}
      </TableCell>
      <TableCell>
        <div className="flex flex-wrap gap-1">
          {"vision" in model && model.vision && (
            <Badge variant="outline">{t("capability_vision")}</Badge>
          )}
          {"reasoning" in model && model.reasoning && (
            <Badge variant="outline">{t("reasoning")}</Badge>
          )}
          {model.hosting && <Badge variant="outline">{model.hosting}</Badge>}
        </div>
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
              {(canEdit || canMigrate) && (supportsDefault || supportsClassification) && (
                <DropdownMenuSeparator />
              )}
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
            model={model as CompletionModelAdmin}
            open={showEdit}
            onOpenChange={setShowEdit}
          />
        )}
        {canMigrate && (
          <MigrateModelDialog
            model={model as CompletionModelAdmin}
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
      </TableCell>
    </TableRow>
  );
}

export function ModelTable({
  models,
  kind,
  classifications,
  securityEnabled
}: {
  models: AdminModel[];
  kind: ModelKind;
  classifications: SecurityClassification[];
  securityEnabled: boolean;
}) {
  const t = useTranslations();
  const groups = groupByProvider(models);

  return (
    <div className="flex flex-col gap-6">
      {groups.map((group) => (
        <div key={group.provider} className="flex flex-col gap-2">
          <h3 className="text-muted-foreground text-sm font-semibold capitalize">
            {group.provider}
          </h3>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-16">{t("status")}</TableHead>
                <TableHead>{t("name")}</TableHead>
                <TableHead>{t("capabilities")}</TableHead>
                {securityEnabled && <TableHead>{t("security_classification")}</TableHead>}
                <TableHead className="w-12" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {group.models.map((model) => (
                <ModelRow
                  key={model.id}
                  model={model}
                  kind={kind}
                  classifications={classifications}
                  securityEnabled={securityEnabled}
                />
              ))}
            </TableBody>
          </Table>
        </div>
      ))}
    </div>
  );
}
