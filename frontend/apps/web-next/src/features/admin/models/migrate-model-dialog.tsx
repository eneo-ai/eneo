"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { browserApi } from "@/lib/api/browser";
import { toastApiError } from "@/lib/api/toast";
import {
  type AdminModel,
  MODEL_MIGRATION_HISTORY_KEY,
  MODELS_KEY,
  type MigratableModelKind,
  adminModelsQueryOptions,
  isMigrationSecurityBlockerCode,
  migrationWarningLabel,
  migrateModelUsage,
  modelLabel,
  modelUsageQueryOptions,
  validateMigrationQueryOptions
} from "./models";

function ImpactSummary({
  data,
  kind
}: {
  data: {
    assistants_count: number;
    apps_count: number;
    services_count: number;
    spaces_count: number;
  };
  kind: MigratableModelKind;
}) {
  const t = useTranslations();

  const rows: [string, number][] =
    kind === "transcription"
      ? [
          [t("apps"), data.apps_count],
          [t("spaces"), data.spaces_count]
        ]
      : [
          [t("assistants"), data.assistants_count],
          [t("apps"), data.apps_count],
          [t("services"), data.services_count],
          [t("spaces"), data.spaces_count]
        ];

  return (
    <div className="bg-muted/40 flex flex-col gap-2 rounded-lg p-3">
      <span className="text-muted-foreground text-xs font-semibold tracking-wider uppercase">
        {t("migration_impact")}
      </span>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="flex justify-between gap-2">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="font-medium tabular-nums">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function Warnings({ warnings, warningCodes }: { warnings: string[]; warningCodes: string[] }) {
  const t = useTranslations();

  if (warnings.length === 0) {
    return <p className="text-muted-foreground text-sm">{t("migration_no_warnings")}</p>;
  }

  return (
    <div className="flex flex-col gap-2" role="alert">
      <span className="text-muted-foreground text-xs font-semibold tracking-wider uppercase">
        {t("migration_warnings")}
      </span>
      <ul className="flex flex-col gap-1.5">
        {warnings.map((warning, index) => (
          <li key={index} className="flex items-start gap-2 text-sm">
            <AlertTriangle aria-hidden="true" className="text-destructive mt-0.5 size-4 shrink-0" />
            <span>{migrationWarningLabel(t, warning, warningCodes[index])}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Migrate all usage of one completion model onto a replacement model. */
export function MigrateModelDialog({
  model,
  kind,
  open,
  onOpenChange
}: {
  model: AdminModel;
  kind: MigratableModelKind;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [targetId, setTargetId] = useState("");
  const [forceOverride, setForceOverride] = useState(false);

  const { data: models } = useQuery({ ...adminModelsQueryOptions(browserApi), enabled: open });
  const usage = useQuery({
    ...modelUsageQueryOptions(browserApi, model.id, kind),
    enabled: open
  });
  const validation = useQuery({
    ...validateMigrationQueryOptions(browserApi, model.id, targetId, kind),
    enabled: open && Boolean(targetId)
  });
  const targetModels =
    kind === "transcription"
      ? (models?.transcription_models ?? [])
      : (models?.completion_models ?? []);
  const targets = targetModels.filter(
    (candidate) =>
      candidate.id !== model.id &&
      candidate.is_org_enabled &&
      !candidate.is_deprecated &&
      !candidate.deprecation_date &&
      !candidate.migrated_to_model_id
  );
  const warningCodes = validation.data?.warning_codes ?? [];
  const warnings = validation.data?.warnings ?? [];
  const hasSecurityBlocker = warningCodes.some(isMigrationSecurityBlockerCode);
  const blocked =
    usage.isPending ||
    usage.isError ||
    validation.isPending ||
    validation.isError ||
    !targetId ||
    (hasSecurityBlocker && !forceOverride);

  const migrate = useMutation({
    mutationFn: () => migrateModelUsage(browserApi, kind, model.id, targetId, forceOverride),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: MODELS_KEY });
      void queryClient.invalidateQueries({ queryKey: MODEL_MIGRATION_HISTORY_KEY });
      void queryClient.invalidateQueries({ queryKey: ["model-usage"] });
      void queryClient.invalidateQueries({ queryKey: ["model-usage-details"] });
      toast.success(t("migration_success"), {
        description: t("migration_used_by", { count: result.migrated_count })
      });
      onOpenChange(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("migrate_model")}</DialogTitle>
          <DialogDescription>{modelLabel(model)}</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-4">
          {usage.data && <ImpactSummary data={usage.data} kind={kind} />}
          {usage.isError && (
            <div className="border-destructive/30 bg-destructive/10 text-destructive flex items-start gap-2 rounded-md border px-3 py-2 text-sm">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              {t("migration_impact_failed")}
            </div>
          )}

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="migration-target">{t("migration_target")}</Label>
            <Select
              value={targetId}
              onValueChange={(value) => {
                setTargetId(value);
                setForceOverride(false);
              }}
            >
              <SelectTrigger id="migration-target" className="w-full">
                <SelectValue placeholder={t("select_target_model")} />
              </SelectTrigger>
              <SelectContent>
                {targets.map((target) => (
                  <SelectItem key={target.id} value={target.id}>
                    {modelLabel(target)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {targetId && validation.isPending && (
            <p className="text-muted-foreground text-sm">{t("validating_models")}</p>
          )}
          {targetId && validation.isError && (
            <div className="border-destructive/30 bg-destructive/10 text-destructive flex items-start gap-2 rounded-md border px-3 py-2 text-sm">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              {t("migration_validation_failed")}
            </div>
          )}
          {targetId && validation.data && (
            <Warnings warnings={warnings} warningCodes={warningCodes} />
          )}

          {hasSecurityBlocker && (
            <label className="border-destructive/30 bg-destructive/10 flex items-start gap-2 rounded-md border px-3 py-2 text-sm">
              <Checkbox
                className="mt-0.5"
                checked={forceOverride}
                onCheckedChange={(checked) => setForceOverride(checked === true)}
              />
              <span>{t("migration_force_override_ack")}</span>
            </label>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("cancel")}
            </Button>
            <Button disabled={blocked || migrate.isPending} onClick={() => migrate.mutate()}>
              {migrate.isPending ? t("saving") : t("migrate")}
            </Button>
          </DialogFooter>
        </div>
      </DialogContent>
    </Dialog>
  );
}
