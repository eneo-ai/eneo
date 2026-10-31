"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "use-intl";
import { useState } from "react";
import {
  FieldProblem,
  fieldProblemProps,
  revealProblems
} from "@/components/composites/field-problem";
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
import { Banner } from "@astryxdesign/core/Banner";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { ModelUsageBreakdown } from "./model-usage-breakdown";
import { browserApi } from "@/lib/api/browser";
import { toastApiError } from "@/lib/api/toast";
import { toast } from "@/lib/toast";
import { modelDisplayName } from "@/lib/models/model-display-name";
import {
  type AdminModel,
  MODEL_MIGRATION_HISTORY_KEY,
  MODELS_KEY,
  type MigratableModelKind,
  adminModelsQueryOptions,
  isMigrationSecurityBlockerCode,
  migrationWarningLabel,
  migrateModelUsage,
  modelUsageQueryOptions,
  modelUsageDetailsQueryOptions,
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
    assistant_templates_count?: number;
    app_templates_count?: number;
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
          [t("migration_summary_assistant_templates"), data.assistant_templates_count ?? 0],
          [t("migration_summary_app_templates"), data.app_templates_count ?? 0],
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

function Warnings({
  title,
  messages,
  status
}: {
  title: string;
  messages: string[];
  status: "error" | "warning" | "info";
}) {
  if (messages.length === 0) return null;
  return (
    <Banner title={title} status={status} collapsible={false}>
      <ul className="flex flex-col gap-1.5">
        {messages.map((message, index) => (
          <li key={index} className="text-sm">
            {message}
          </li>
        ))}
      </ul>
    </Banner>
  );
}

/** Migrate all usage of one completion model onto a replacement model. */
type MigrateModelDialogProps = {
  model: AdminModel;
  kind: MigratableModelKind;
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

export function MigrateModelDialog(props: MigrateModelDialogProps) {
  return props.open ? (
    <MigrateModelForm key={`${props.kind}:${props.model.id}`} {...props} />
  ) : null;
}

function MigrateModelForm({ model, kind, open, onOpenChange }: MigrateModelDialogProps) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [targetId, setTargetId] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const modelsQuery = useQuery({ ...adminModelsQueryOptions(browserApi), enabled: open });
  const models = modelsQuery.data;
  const details = useQuery({
    ...modelUsageDetailsQueryOptions(browserApi, model.id, kind),
    enabled: open
  });
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
      candidate.provider_id != null &&
      candidate.is_org_enabled &&
      !candidate.is_deprecated &&
      !candidate.deprecation_date &&
      !candidate.migrated_to_model_id
  );
  const warningCodes = validation.data?.warning_codes ?? [];
  const warnings = validation.data?.warnings ?? [];
  const messages = Array.from(
    { length: Math.max(warnings.length, warningCodes.length) },
    (_, index) => {
      const code = warningCodes[index];
      return {
        text: migrationWarningLabel(t, warnings[index] ?? code ?? "", code),
        severity: isMigrationSecurityBlockerCode(code)
          ? "security"
          : code?.split(":")[0] === "kwargs_reset"
            ? "info"
            : "warning"
      };
    }
  );
  const blockers = messages
    .filter((message) => message.severity === "security")
    .map((message) => message.text);
  const compatibility = messages
    .filter((message) => message.severity === "warning")
    .map((message) => message.text);
  const information = messages
    .filter((message) => message.severity === "info")
    .map((message) => message.text);
  const hasSecurityBlocker = blockers.length > 0;
  // Spaces are re-pointed too, but compatibility warnings concern resources.
  const hasResourceImpact = (details.data?.total ?? 0) > 0;
  const needsAck = hasSecurityBlocker || (hasResourceImpact && compatibility.length > 0);
  const alreadyMigrated = "migrated_to_model_id" in model && Boolean(model.migrated_to_model_id);
  const unavailable =
    alreadyMigrated ||
    modelsQuery.isPending ||
    modelsQuery.isError ||
    usage.isPending ||
    usage.isError ||
    details.isPending ||
    details.isError ||
    (targetId !== "" && (validation.isPending || validation.isError));
  const targetProblem = targets.some((target) => target.id === targetId)
    ? null
    : t("form_problem_choose_target_model");
  const overrideProblem =
    needsAck && !acknowledged
      ? t(
          hasSecurityBlocker
            ? "form_problem_confirm_override"
            : "form_problem_confirm_migration_warning"
        )
      : null;
  const shown = (problem: string | null) => (submitted ? problem : null);

  const migrate = useMutation({
    mutationFn: async () => {
      const result = await migrateModelUsage(browserApi, kind, model.id, {
        to_model_id: targetId,
        confirm_migration: !needsAck || acknowledged,
        force_override: hasSecurityBlocker && acknowledged
      });
      if (!result.success) throw new Error(t("migration_failed"));
      return result;
    },
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

  // A missing target, or an unconfirmed override of a security blocker, shows
  // at its field on Migrate, which takes focus.
  function submit() {
    if (unavailable || migrate.isPending) return;
    const firstProblem = targetProblem
      ? "migration-target"
      : overrideProblem
        ? "migration-force-override"
        : null;
    if (firstProblem) {
      revealProblems(() => setSubmitted(true), firstProblem);
      return;
    }
    migrate.mutate();
  }

  function changeOpen(next: boolean) {
    if (migrate.isPending) return;
    if (!next) setSubmitted(false);
    onOpenChange(next);
  }

  return (
    <Dialog open={open} onOpenChange={changeOpen}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("migrate_model")}</DialogTitle>
          <DialogDescription>{modelDisplayName(model)}</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-4">
          {alreadyMigrated && (
            <p className="text-muted-foreground text-sm">{t("model_tooltip_migrated")}</p>
          )}
          <QueryStateBoundary query={modelsQuery}>{() => null}</QueryStateBoundary>
          <QueryStateBoundary query={usage} errorTitle={t("migration_impact_failed")}>
            {(data) => <ImpactSummary data={data} kind={kind} />}
          </QueryStateBoundary>
          <QueryStateBoundary query={details} errorTitle={t("migration_impact_failed")}>
            {(data) => <ModelUsageBreakdown data={data} />}
          </QueryStateBoundary>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="migration-target">{t("migration_target")}</Label>
            <Select
              disabled={migrate.isPending}
              value={targetId}
              onValueChange={(value) => {
                setTargetId(value);
                setAcknowledged(false);
                setSubmitted(false);
              }}
            >
              <SelectTrigger
                id="migration-target"
                className="w-full"
                {...fieldProblemProps("migration-target", shown(targetProblem))}
              >
                <SelectValue placeholder={t("select_target_model")} />
              </SelectTrigger>
              <SelectContent>
                {targets.map((target) => (
                  <SelectItem key={target.id} value={target.id}>
                    {modelDisplayName(target)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <FieldProblem id="migration-target" problem={shown(targetProblem)} />
          </div>

          {targetId && (
            <QueryStateBoundary query={validation} errorTitle={t("migration_validation_failed")}>
              {() => (
                <>
                  <Warnings
                    title={t("migration_blocked_title")}
                    messages={blockers}
                    status="error"
                  />
                  {hasResourceImpact && (
                    <>
                      <Warnings
                        title={t("migration_warnings_title")}
                        messages={compatibility}
                        status="warning"
                      />
                      <Warnings
                        title={t("migration_info_title")}
                        messages={information}
                        status="info"
                      />
                    </>
                  )}
                  {messages.length === 0 && (
                    <p className="text-muted-foreground text-sm">{t("migration_no_warnings")}</p>
                  )}
                </>
              )}
            </QueryStateBoundary>
          )}

          {needsAck && (
            <div className="flex flex-col gap-1.5">
              <label
                className={
                  hasSecurityBlocker
                    ? "border-destructive/30 bg-destructive/10 flex items-start gap-2 rounded-md border px-3 py-2 text-sm"
                    : "border-border bg-muted/40 flex items-start gap-2 rounded-md border px-3 py-2 text-sm"
                }
              >
                <Checkbox
                  id="migration-force-override"
                  className="mt-0.5"
                  disabled={migrate.isPending}
                  checked={acknowledged}
                  onCheckedChange={(checked) => setAcknowledged(checked === true)}
                  {...fieldProblemProps("migration-force-override", shown(overrideProblem))}
                />
                <span>
                  {t(
                    hasSecurityBlocker
                      ? "migration_force_override_ack"
                      : "migrate_model_confirm_label"
                  )}
                </span>
              </label>
              <FieldProblem id="migration-force-override" problem={shown(overrideProblem)} />
            </div>
          )}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={migrate.isPending}
              onClick={() => changeOpen(false)}
            >
              {t("cancel")}
            </Button>
            {/* Disabled only while there is nothing to decide on; busy, it keeps focus. */}
            <Button
              disabled={unavailable}
              aria-busy={migrate.isPending || undefined}
              onClick={submit}
            >
              {migrate.isPending ? t("saving") : t("migrate")}
            </Button>
          </DialogFooter>
        </div>
      </DialogContent>
    </Dialog>
  );
}
