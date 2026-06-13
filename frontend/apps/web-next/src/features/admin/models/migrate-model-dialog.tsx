"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
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
  type CompletionModelAdmin,
  MODELS_KEY,
  adminModelsQueryOptions,
  migrateModelUsage,
  modelLabel,
  modelUsageQueryOptions,
  validateMigrationQueryOptions
} from "./models";

function ImpactSummary({ modelId }: { modelId: string }) {
  const t = useTranslations();
  const { data } = useQuery(modelUsageQueryOptions(browserApi, modelId));
  if (!data) return null;

  const rows: [string, number][] = [
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

function Warnings({ modelId, toModelId }: { modelId: string; toModelId: string }) {
  const t = useTranslations();
  const { data, isPending } = useQuery({
    ...validateMigrationQueryOptions(browserApi, modelId, toModelId),
    enabled: Boolean(toModelId)
  });
  if (!toModelId || isPending || !data) return null;

  if (data.warnings.length === 0) {
    return <p className="text-muted-foreground text-sm">{t("migration_no_warnings")}</p>;
  }

  return (
    <div className="flex flex-col gap-2" role="alert">
      <span className="text-muted-foreground text-xs font-semibold tracking-wider uppercase">
        {t("migration_warnings")}
      </span>
      <ul className="flex flex-col gap-1.5">
        {data.warnings.map((warning, index) => (
          <li key={index} className="flex items-start gap-2 text-sm">
            <AlertTriangle aria-hidden="true" className="text-destructive mt-0.5 size-4 shrink-0" />
            <span>{warning}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Migrate all usage of one completion model onto a replacement model. */
export function MigrateModelDialog({
  model,
  open,
  onOpenChange
}: {
  model: CompletionModelAdmin;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [targetId, setTargetId] = useState("");

  const { data: models } = useQuery({ ...adminModelsQueryOptions(browserApi), enabled: open });
  const targets = (models?.completion_models ?? []).filter(
    (candidate) => candidate.id !== model.id && !candidate.migrated_to_model_id
  );

  const migrate = useMutation({
    mutationFn: () => migrateModelUsage(browserApi, model.id, targetId),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: MODELS_KEY });
      void queryClient.invalidateQueries({ queryKey: ["model-usage", model.id] });
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
          <ImpactSummary modelId={model.id} />

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="migration-target">{t("migration_target")}</Label>
            <Select value={targetId} onValueChange={setTargetId}>
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

          {targetId && <Warnings modelId={model.id} toModelId={targetId} />}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("cancel")}
            </Button>
            <Button disabled={!targetId || migrate.isPending} onClick={() => migrate.mutate()}>
              {migrate.isPending ? t("saving") : t("migrate")}
            </Button>
          </DialogFooter>
        </div>
      </DialogContent>
    </Dialog>
  );
}
