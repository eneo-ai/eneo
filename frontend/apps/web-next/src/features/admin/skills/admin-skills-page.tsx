"use client";

import { useQuery } from "@tanstack/react-query";
import { CircleAlert, RotateCcw } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { PageHeader } from "@/components/composites/page-header";
import { SettingsGroup } from "@/components/composites/settings-rows";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import {
  draftValid,
  draftsEqual,
  fieldValid,
  policyDraft,
  type SkillRuntimeModelProjections,
  type SkillRuntimePolicy,
  type SkillRuntimePolicyDraft
} from "./skill-runtime-policy";

export function AdminSkillsPage() {
  const t = useTranslations();
  const policy = useQuery({
    queryKey: ["skill-runtime-policy"],
    queryFn: () => unwrap(browserApi.GET("/api/v1/settings/skills/runtime-policy")),
    retry: false,
    refetchOnWindowFocus: false
  });
  const projections = useQuery({
    queryKey: ["skill-runtime-model-projections"],
    queryFn: () =>
      unwrap(browserApi.GET("/api/v1/settings/skills/runtime-policy/model-projections")),
    retry: false,
    refetchOnWindowFocus: false
  });

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 pb-16">
      <PageHeader title={t("admin_skills_title")} tour="admin-skills" />
      <p className="text-muted-foreground max-w-3xl text-sm">{t("admin_skills_subtitle")}</p>
      {policy.isPending || projections.isPending ? (
        <p role="status" className="text-muted-foreground text-sm">
          {t("loading")}
        </p>
      ) : policy.isError ? (
        <Alert variant="destructive" role="alert">
          <CircleAlert className="size-4" />
          <AlertTitle>{t("request_failed")}</AlertTitle>
          <AlertDescription>
            <Button variant="outline" size="sm" onClick={() => void policy.refetch()}>
              {t("retry")}
            </Button>
          </AlertDescription>
        </Alert>
      ) : (
        <PolicyEditor initialPolicy={policy.data} initialProjections={projections.data ?? null} />
      )}
    </div>
  );
}

function PolicyEditor({
  initialPolicy,
  initialProjections
}: {
  initialPolicy: SkillRuntimePolicy;
  initialProjections: SkillRuntimeModelProjections | null;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const [policy, setPolicy] = useState(initialPolicy);
  const [draft, setDraft] = useState<SkillRuntimePolicyDraft>(() => policyDraft(initialPolicy));
  const [modelProjections, setModelProjections] = useState(initialProjections);
  const [busy, setBusy] = useState<"save" | "reset" | null>(null);
  const [resetOpen, setResetOpen] = useState(false);
  const [error, setError] = useState<"save" | "reset" | null>(null);
  const [status, setStatus] = useState<"saved" | "reset" | null>(null);

  const dirty = !draftsEqual(draft, policyDraft(policy));
  const valid = draftValid(draft, policy.editable_bounds);

  async function update(kind: "save" | "reset") {
    if (busy || (kind === "save" && !dirty)) return;
    setBusy(kind);
    setError(null);
    setStatus(null);
    try {
      let next: SkillRuntimePolicy;
      if (kind === "save") {
        if (!draftValid(draft, policy.editable_bounds)) return;
        next = await unwrap(
          browserApi.PUT("/api/v1/settings/skills/runtime-policy", { body: draft })
        );
      } else {
        next = await unwrap(browserApi.POST("/api/v1/settings/skills/runtime-policy/reset"));
      }
      setPolicy(next);
      setDraft(policyDraft(next));
      const projection = await unwrap(
        browserApi.GET("/api/v1/settings/skills/runtime-policy/model-projections")
      ).catch(() => null);
      setModelProjections(projection);
      setStatus(kind === "save" ? "saved" : "reset");
    } catch {
      setError(kind);
    } finally {
      setBusy(null);
      setResetOpen(false);
    }
  }

  return (
    <SettingsGroup
      id="skill-runtime"
      title={t("skills_runtime_policy_title")}
      description={t("skills_runtime_policy_description")}
      headerEnd={
        <Badge variant={policy.selective_activation_enabled ? "default" : "outline"}>
          {t(
            policy.selective_activation_enabled
              ? "admin_skills_runtime_summary_on"
              : "admin_skills_runtime_summary_off"
          )}
        </Badge>
      }
    >
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="text-sm font-medium">{t("skills_runtime_policy_selective_title")}</p>
          <p className="text-muted-foreground text-sm">
            {t("skills_runtime_policy_selective_description")}
          </p>
        </div>
        <Switch
          checked={draft.selective_activation_enabled}
          disabled={busy !== null}
          aria-label={t("skills_runtime_policy_selective_title")}
          onCheckedChange={(checked) =>
            setDraft((current) => ({ ...current, selective_activation_enabled: checked }))
          }
        />
      </div>
      <div className="grid gap-5 border-t pt-5 md:grid-cols-3">
        <PolicyNumberField
          id="max-attached-skills"
          label={t("skills_runtime_policy_max_attached")}
          description={t("skills_runtime_policy_max_attached_description")}
          value={draft.max_attached_skills}
          bounds={policy.editable_bounds.max_attached_skills}
          disabled={busy !== null}
          onChange={(value) => setDraft((current) => ({ ...current, max_attached_skills: value }))}
        />
        <PolicyNumberField
          id="context-share-percent"
          label={t("skills_runtime_policy_context_share")}
          description={t("skills_runtime_policy_context_share_description")}
          value={draft.context_share_percent}
          bounds={policy.editable_bounds.context_share_percent}
          disabled={busy !== null}
          onChange={(value) =>
            setDraft((current) => ({ ...current, context_share_percent: value }))
          }
        />
        <PolicyNumberField
          id="max-activations"
          label={t("skills_runtime_policy_max_activations")}
          description={t("skills_runtime_policy_max_activations_description")}
          value={draft.max_activations_per_turn}
          bounds={policy.editable_bounds.max_activations_per_turn}
          disabled={busy !== null}
          onChange={(value) =>
            setDraft((current) => ({ ...current, max_activations_per_turn: value }))
          }
        />
      </div>
      {error && (
        <Alert variant="destructive" role="alert">
          <CircleAlert className="size-4" />
          <AlertTitle>
            {t(
              error === "reset"
                ? "skills_runtime_policy_reset_error"
                : "skills_runtime_policy_save_error"
            )}
          </AlertTitle>
        </Alert>
      )}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
        <p role="status" className="text-muted-foreground text-sm" aria-live="polite">
          {status === "saved"
            ? t("skills_runtime_policy_saved")
            : status === "reset"
              ? t("skills_runtime_policy_reset_done")
              : ""}
        </p>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" disabled={busy !== null} onClick={() => setResetOpen(true)}>
            <RotateCcw className="size-4" />
            {t("skills_runtime_policy_reset")}
          </Button>
          <Button disabled={busy !== null || !dirty || !valid} onClick={() => void update("save")}>
            {busy === "save" ? t("skills_runtime_policy_saving") : t("skills_runtime_policy_save")}
          </Button>
        </div>
      </div>
      <section className="space-y-3 border-t pt-5" aria-labelledby="skill-models-heading">
        <h3 id="skill-models-heading" className="font-medium">
          {t("skills_runtime_models_title")}
        </h3>
        {modelProjections === null ? (
          <Alert>
            <CircleAlert className="size-4" />
            <AlertTitle>{t("skills_runtime_models_unavailable_title")}</AlertTitle>
            <AlertDescription>
              {t("skills_runtime_models_unavailable_description")}
            </AlertDescription>
          </Alert>
        ) : modelProjections.models.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("skills_runtime_models_empty")}</p>
        ) : (
          <>
            <p className="text-muted-foreground text-sm">
              {t("skills_runtime_models_description", {
                percent: String(policy.context_share_percent)
              })}
            </p>
            <div
              className="max-h-72 overflow-auto rounded-lg border"
              role="region"
              tabIndex={0}
              aria-label={t("skills_runtime_models_region", {
                count: String(modelProjections.models.length)
              })}
            >
              <table className="w-full min-w-[44rem] text-sm">
                <thead className="bg-background sticky top-0">
                  <tr className="border-b text-left">
                    <th className="p-3">{t("skills_runtime_models_model")}</th>
                    <th className="p-3 text-right">{t("skills_runtime_models_input_window")}</th>
                    <th className="p-3 text-right">{t("skills_runtime_models_skill_budget")}</th>
                    <th className="p-3">{t("skills_runtime_models_tool_calling")}</th>
                  </tr>
                </thead>
                <tbody>
                  {modelProjections.models.map((model) => (
                    <tr key={model.completion_model_id} className="border-b last:border-0">
                      <td className="p-3 font-medium">
                        {model.nickname ?? model.name}
                        {model.nickname && (
                          <span className="text-muted-foreground block text-xs">{model.name}</span>
                        )}
                      </td>
                      <td className="p-3 text-right tabular-nums">
                        {t("skills_runtime_tokens", {
                          count: model.max_input_tokens.toLocaleString(locale)
                        })}
                      </td>
                      <td className="p-3 text-right tabular-nums">
                        {t("skills_runtime_tokens", {
                          count: model.skill_context_token_allowance.toLocaleString(locale)
                        })}
                      </td>
                      <td className="p-3">
                        <Badge variant={model.supports_tool_calling ? "secondary" : "outline"}>
                          {t(
                            model.supports_tool_calling
                              ? "skills_runtime_models_supported"
                              : "skills_runtime_models_not_supported"
                          )}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>
      <ConfirmDialogControlled
        open={resetOpen}
        onOpenChange={(open) => {
          if (!busy) setResetOpen(open);
        }}
        title={t("skills_runtime_policy_reset_title")}
        description={t("skills_runtime_policy_reset_description")}
        confirmLabel={t("skills_runtime_policy_reset")}
        variant="default"
        pending={busy !== null}
        onConfirm={() => void update("reset")}
      />
    </SettingsGroup>
  );
}

function PolicyNumberField({
  id,
  label,
  description,
  value,
  bounds,
  disabled,
  onChange
}: {
  id: string;
  label: string;
  description: string;
  value: number | null;
  bounds: { minimum: number; maximum: number };
  disabled: boolean;
  onChange: (value: number | null) => void;
}) {
  const t = useTranslations();
  const valid = fieldValid(value, bounds);
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type="number"
        step="1"
        min={bounds.minimum}
        max={bounds.maximum}
        value={value ?? ""}
        aria-invalid={!valid}
        disabled={disabled}
        onChange={(event) =>
          onChange(event.target.value === "" ? null : Number(event.target.value))
        }
      />
      <p className="text-muted-foreground text-xs">{description}</p>
      <p className="text-muted-foreground text-xs tabular-nums">
        {t("skills_runtime_policy_allowed_range", {
          minimum: String(bounds.minimum),
          maximum: String(bounds.maximum)
        })}
      </p>
      {!valid && (
        <p className="text-destructive text-xs" role="alert">
          {t("skills_runtime_policy_invalid")}
        </p>
      )}
    </div>
  );
}
