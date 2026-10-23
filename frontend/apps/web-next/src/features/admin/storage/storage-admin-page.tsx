"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, Database, HardDrive, Info, RefreshCw } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";
import { flushSync } from "react-dom";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { PageHeader } from "@/components/composites/page-header";
import { SettingsGroup } from "@/components/composites/settings-rows";
import { useAppContext } from "@/components/providers/app-context";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError, unwrap } from "@/lib/api/errors";
import { toast } from "@/lib/toast";
import { ByteLimitField } from "./byte-limit-field";
import { StorageConnectionSection } from "./storage-connection-section";
import { StorageContent } from "./storage-content";
import {
  classifyPolicyRefresh,
  isDirtyPolicyDraft,
  isValidByteLimit,
  isValidPolicyDraft,
  policyDraft,
  type DeploymentPolicy,
  type PolicyUpdate,
  type StorageKind
} from "./storage-policy";

const LIMIT_FIELDS = [
  {
    field: "session_file_limit_bytes",
    id: "session-file-limit",
    label: "storage_limit_session_file",
    help: "storage_limit_bytes_help"
  },
  {
    field: "session_image_limit_bytes",
    id: "session-image-limit",
    label: "storage_limit_session_image",
    help: "storage_limit_bytes_help"
  },
  {
    field: "knowledge_file_limit_bytes",
    id: "knowledge-file-limit",
    label: "storage_limit_knowledge_file",
    help: "storage_limit_bytes_help"
  },
  {
    field: "transcription_audio_limit_bytes",
    id: "transcription-audio-limit",
    label: "storage_limit_transcription_audio",
    help: "storage_limit_audio_help"
  }
] as const;

export function StorageAdminPage() {
  const t = useTranslations();
  const { can } = useAppContext();
  const policy = useQuery({
    queryKey: ["storage-deployment-policy"],
    queryFn: () => unwrap(browserApi.GET("/api/v1/admin/object-content-policy")),
    retry: false,
    refetchOnWindowFocus: false
  });

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 pb-16">
      <PageHeader title={t("storage_settings_title")} tour="admin-storage" />
      {policy.isPending ? (
        <div className="space-y-4" aria-busy="true">
          <Skeleton className="h-5 w-56" />
          <Skeleton className="h-40 w-full" />
          <span className="sr-only">{t("storage_settings_loading")}</span>
        </div>
      ) : policy.isError ? (
        <Alert variant="destructive" role="alert">
          <CircleAlert className="size-4" />
          <AlertTitle>{t("storage_settings_load_error_title")}</AlertTitle>
          <AlertDescription>
            <p>{t("storage_settings_load_error_description")}</p>
            <Button variant="outline" size="sm" onClick={() => void policy.refetch()}>
              {t("retry")}
            </Button>
          </AlertDescription>
        </Alert>
      ) : (
        <StoragePolicyEditor initialPolicy={policy.data} canEdit={can("storage")} />
      )}
    </div>
  );
}

function StoragePolicyEditor({
  initialPolicy,
  canEdit: allowed
}: {
  initialPolicy: DeploymentPolicy;
  canEdit: boolean;
}) {
  const t = useTranslations();
  const router = useRouter();
  const queryClient = useQueryClient();
  const locale = useLocale();
  const [baseline, setBaseline] = useState(initialPolicy);
  const [draft, setDraft] = useState<PolicyUpdate>(() => policyDraft(initialPolicy));
  const [reloading, setReloading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [stale, setStale] = useState(false);
  const [targetUnavailable, setTargetUnavailable] = useState(false);
  const [saveOutcomeUnknown, setSaveOutcomeUnknown] = useState(false);
  const [authorityRevoked, setAuthorityRevoked] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [showTechnical, setShowTechnical] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const revokeAuthority = useCallback(() => setAuthorityRevoked(true), []);

  const canEdit = allowed && !authorityRevoked;
  const dirty = isDirtyPolicyDraft(draft, baseline);
  const valid = isValidPolicyDraft(draft);
  const objectStoreCapability = baseline.capabilities.find(
    (capability) => capability.target === "object_store"
  );
  const objectStoreUnavailable = objectStoreCapability?.selectable !== true;
  const targetChanged = draft.new_write_storage_target !== baseline.policy.new_write_storage_target;
  const selectedObjectStoreDegraded =
    baseline.policy.new_write_storage_target === "object_store" &&
    objectStoreCapability?.readiness_code !== "ready";
  const interactionUnavailable = reloading || saving;
  // States that need the administrator's attention elsewhere first (a reload,
  // a newer revision, an unknown outcome); each has its own message.
  const saveBlocked = !canEdit || !dirty || reloading || stale || saveOutcomeUnknown;
  const limitProblem = (field: (typeof LIMIT_FIELDS)[number]["field"]) =>
    submitted && !isValidByteLimit(draft[field]) ? t("storage_limit_invalid") : null;

  const targetLabel = (target: StorageKind) =>
    t(
      target === "postgres_inline"
        ? "storage_target_postgres_inline"
        : "storage_target_object_store"
    );
  const bytesLabel = (value: number) => {
    const unit =
      value % 1024 ** 3 === 0
        ? "GB"
        : value % 1024 ** 2 === 0
          ? "MB"
          : value % 1024 === 0
            ? "KB"
            : "B";
    const units = { B: 1, KB: 1024, MB: 1024 ** 2, GB: 1024 ** 3 };
    return `${new Intl.NumberFormat(locale).format(value / units[unit])} ${t(`storage_unit_${unit.toLowerCase()}`)}`;
  };

  async function reload(preserveDraft = false) {
    if (interactionUnavailable) return;
    setReloading(true);
    setLoadError(false);
    try {
      const next = await unwrap(browserApi.GET("/api/v1/admin/object-content-policy"));
      const outcome = classifyPolicyRefresh(
        baseline.policy.revision,
        next.policy.revision,
        preserveDraft
      );
      if (outcome === "ignore") return;
      if (outcome === "stale") {
        setStale(true);
        return;
      }
      setBaseline(next);
      if (!preserveDraft) setDraft(policyDraft(next));
      setStale(false);
      setTargetUnavailable(false);
      setSaveOutcomeUnknown(false);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["storage-inventory"] }),
        queryClient.invalidateQueries({ queryKey: ["storage-moves"] })
      ]);
    } catch (error) {
      if (error instanceof EneoApiError && error.status === 403) setAuthorityRevoked(true);
      setLoadError(true);
    } finally {
      setReloading(false);
    }
  }

  // Save is not disabled for a limit out of range: it shows at its field,
  // which takes focus. Busy, Save keeps focus and a second press is ignored.
  function requestSave() {
    if (saving || saveBlocked) return;
    const invalid = LIMIT_FIELDS.find(({ field }) => !isValidByteLimit(draft[field]));
    if (invalid) {
      // Rendered before focus moves, so the field is read with its problem.
      flushSync(() => setSubmitted(true));
      document.getElementById(invalid.id)?.focus();
      return;
    }
    if (targetChanged) setConfirmOpen(true);
    else void save();
  }

  async function save() {
    if (saving || saveBlocked || !valid) return;
    setSaving(true);
    setStale(false);
    setTargetUnavailable(false);
    setSaveOutcomeUnknown(false);
    try {
      const updated = await unwrap(
        browserApi.PUT("/api/v1/admin/object-content-policy", {
          body: { ...draft, expected_revision: baseline.policy.revision }
        })
      );
      setBaseline(updated);
      setDraft(policyDraft(updated));
      setSubmitted(false);
      toast.success(t("storage_settings_save_success"));
    } catch (error) {
      if (error instanceof EneoApiError && error.status === 403) setAuthorityRevoked(true);
      else if (error instanceof EneoApiError && error.code === 9046) setStale(true);
      else if (error instanceof EneoApiError && error.code === 9047) setTargetUnavailable(true);
      else setSaveOutcomeUnknown(true);
    } finally {
      setSaving(false);
      setConfirmOpen(false);
    }
  }

  function discard() {
    setDraft(policyDraft(baseline));
    setSubmitted(false);
    setStale(false);
    setTargetUnavailable(false);
    setSaveOutcomeUnknown(false);
  }

  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-3xl space-y-1">
          <p className="text-muted-foreground text-sm leading-6">
            {t("storage_settings_description")}
          </p>
          <p className="text-muted-foreground text-xs">
            {t("storage_settings_last_changed", {
              date: new Intl.DateTimeFormat(locale, {
                dateStyle: "long",
                timeStyle: "short"
              }).format(new Date(baseline.policy.updated_at)),
              actor: t(
                baseline.policy.updated_by_actor === "migration"
                  ? "storage_policy_actor_migration"
                  : "storage_policy_actor_storage_admin"
              )
            })}
          </p>
        </div>
        <Button
          variant="outline"
          disabled={interactionUnavailable}
          onClick={() => void reload(dirty)}
        >
          <RefreshCw className={`size-4 ${reloading ? "animate-spin" : ""}`} />
          {t("storage_settings_refresh_status")}
        </Button>
      </div>

      {!canEdit && (
        <Alert>
          <Info className="size-4" />
          <AlertTitle>{t("storage_settings_read_only_title")}</AlertTitle>
          <AlertDescription>{t("storage_settings_read_only_description")}</AlertDescription>
        </Alert>
      )}

      {canEdit && (
        <StorageContent
          policy={baseline}
          dirtyPolicyDraft={dirty}
          policyBusy={interactionUnavailable}
          onAuthorityRevoked={() => setAuthorityRevoked(true)}
          onPolicyPaused={(previousRevision, nextRevision, paused) => {
            if (baseline.policy.revision === previousRevision) {
              setBaseline((current) => ({
                ...current,
                policy: { ...current.policy, revision: nextRevision, moves_paused: paused }
              }));
            } else {
              void reload(dirty);
            }
          }}
          onRefreshPolicy={reload}
        />
      )}

      <StorageConnectionSection
        capability={objectStoreCapability}
        canEdit={canEdit}
        onAuthorityRevoked={revokeAuthority}
        onConnectionChanged={async () => {
          await reload(dirty);
          router.refresh();
        }}
      />

      {(stale || loadError || targetUnavailable || saveOutcomeUnknown) && (
        <Alert variant="destructive" role="alert" aria-live="assertive">
          <CircleAlert className="size-4" />
          <AlertTitle>
            {t(
              stale
                ? "storage_settings_stale_title"
                : loadError
                  ? "storage_settings_reload_error_title"
                  : targetUnavailable
                    ? "storage_settings_target_unavailable_title"
                    : "storage_settings_save_outcome_unknown_title"
            )}
          </AlertTitle>
          <AlertDescription>
            <p>
              {t(
                stale
                  ? "storage_settings_stale_description"
                  : loadError
                    ? "storage_settings_reload_error_description"
                    : targetUnavailable
                      ? "storage_settings_target_unavailable_description"
                      : "storage_settings_save_outcome_unknown_description"
              )}
            </p>
            {(stale || saveOutcomeUnknown) && (
              <Button
                variant="outline"
                size="sm"
                disabled={interactionUnavailable}
                onClick={() => void reload()}
              >
                {t("storage_settings_reload_latest")}
              </Button>
            )}
          </AlertDescription>
        </Alert>
      )}

      <SettingsGroup
        title={t("storage_settings_target_title")}
        description={t("storage_settings_target_description")}
      >
        {selectedObjectStoreDegraded && (
          <Alert variant="destructive">
            <CircleAlert className="size-4" />
            <AlertTitle>{t("storage_settings_selected_target_degraded_title")}</AlertTitle>
            <AlertDescription>
              {t("storage_settings_selected_target_degraded_description")}
            </AlertDescription>
          </Alert>
        )}
        <div className="text-muted-foreground flex items-start gap-3 text-sm">
          <Info className="text-primary mt-0.5 size-4 shrink-0" />
          <div className="space-y-1">
            <p className="text-foreground font-medium">
              {t("storage_settings_new_writes_only_title")}
            </p>
            <p>{t("storage_settings_no_move_notice")}</p>
            <p>{t("storage_settings_no_fallback_notice")}</p>
          </div>
        </div>
        {canEdit ? (
          <fieldset disabled={interactionUnavailable} className="grid gap-3 sm:grid-cols-2">
            <legend className="sr-only">{t("storage_settings_target_title")}</legend>
            {(["postgres_inline", "object_store"] as const).map((target) => {
              const unavailable = target === "object_store" && objectStoreUnavailable;
              const selected = draft.new_write_storage_target === target;
              return (
                <label
                  key={target}
                  className={`flex cursor-pointer items-start gap-3 rounded-lg border p-4 ${selected ? "border-primary bg-accent" : ""} ${unavailable ? "opacity-60" : ""}`}
                >
                  <input
                    type="radio"
                    name="storage-target"
                    value={target}
                    checked={selected}
                    disabled={unavailable}
                    onChange={() =>
                      setDraft((current) => ({ ...current, new_write_storage_target: target }))
                    }
                    className="mt-1"
                  />
                  {target === "postgres_inline" ? (
                    <Database className="mt-0.5 size-5 shrink-0" />
                  ) : (
                    <HardDrive className="mt-0.5 size-5 shrink-0" />
                  )}
                  <span className="space-y-1">
                    <span className="flex flex-wrap items-center gap-2 font-medium">
                      {targetLabel(target)}
                      {baseline.policy.new_write_storage_target === target && (
                        <Badge variant="outline">{t("storage_overview_active")}</Badge>
                      )}
                    </span>
                    <span className="text-muted-foreground block text-sm">
                      {t(
                        target === "postgres_inline"
                          ? "storage_target_postgres_inline_description"
                          : "storage_target_object_store_description"
                      )}
                    </span>
                    {unavailable && (
                      <span className="text-muted-foreground block text-xs">
                        {objectStoreCapability
                          ? t(`storage_readiness_${objectStoreCapability.readiness_code}`)
                          : t("storage_inventory_not_available")}
                      </span>
                    )}
                  </span>
                </label>
              );
            })}
          </fieldset>
        ) : (
          <p className="font-medium">{targetLabel(baseline.policy.new_write_storage_target)}</p>
        )}
        <p className="text-muted-foreground text-sm">{t("storage_settings_target_help")}</p>
      </SettingsGroup>

      <SettingsGroup
        title={t("storage_settings_limits_title")}
        description={t("storage_settings_limits_description")}
      >
        {canEdit ? (
          <div className="grid gap-5 sm:grid-cols-2">
            {LIMIT_FIELDS.map(({ field, id, label, help }) => (
              <ByteLimitField
                key={`${baseline.policy.revision}-${field}`}
                id={id}
                label={t(label)}
                description={t(help)}
                bytes={draft[field]}
                storedBytes={baseline.policy[field]}
                problem={limitProblem(field)}
                disabled={interactionUnavailable}
                onChange={(bytes) => setDraft((current) => ({ ...current, [field]: bytes }))}
              />
            ))}
          </div>
        ) : (
          <dl className="grid gap-5 sm:grid-cols-2">
            {LIMIT_FIELDS.map(({ field, label }) => (
              <div key={field}>
                <dt className="text-sm font-medium">{t(label)}</dt>
                <dd className="text-muted-foreground text-sm">
                  {bytesLabel(baseline.policy[field])}
                </dd>
              </div>
            ))}
          </dl>
        )}
        <div>
          <Button
            variant="ghost"
            size="sm"
            aria-expanded={showTechnical}
            onClick={() => setShowTechnical((current) => !current)}
          >
            {showTechnical
              ? t("storage_settings_limits_hide_technical")
              : t("storage_settings_limits_show_technical")}
          </Button>
          {showTechnical && (
            <div className="mt-3 overflow-x-auto rounded-lg border">
              <table className="w-full min-w-[720px] text-sm">
                <caption className="sr-only">{t("storage_effective_limits_caption")}</caption>
                <thead>
                  <tr className="border-b text-left">
                    <th className="p-3">{t("storage_effective_limits_use_case")}</th>
                    <th className="p-3">{t("storage_effective_limits_configured")}</th>
                    <th className="p-3">{t("storage_effective_limits_effective")}</th>
                    <th className="p-3">{t("storage_effective_limits_target")}</th>
                    <th className="p-3">{t("storage_effective_limits_ceiling")}</th>
                    <th className="p-3">{t("storage_effective_limits_source")}</th>
                  </tr>
                </thead>
                <tbody>
                  {baseline.limits.map((limit) => (
                    <tr key={limit.use_case} className="border-b last:border-0">
                      <td className="p-3 font-medium">{t(`storage_use_case_${limit.use_case}`)}</td>
                      <td className="p-3">{bytesLabel(limit.configured_bytes)}</td>
                      <td className="p-3">{bytesLabel(limit.effective_bytes)}</td>
                      <td className="p-3">{targetLabel(limit.storage_target)}</td>
                      <td className="p-3">
                        {limit.operator_ceiling_bytes === null
                          ? t("storage_effective_limits_no_ceiling")
                          : bytesLabel(limit.operator_ceiling_bytes)}
                      </td>
                      <td className="p-3">
                        {t(
                          limit.constraining_source === "operator_ceiling"
                            ? "storage_constraint_operator_ceiling"
                            : "storage_constraint_admin_policy"
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
        {canEdit && (
          <p role="status" className="text-muted-foreground text-sm">
            {dirty ? t("storage_settings_unsaved_changes") : t("storage_settings_no_changes")}
          </p>
        )}
      </SettingsGroup>

      {canEdit && dirty && (
        <div className="bg-card sticky bottom-4 z-20 flex flex-wrap items-center justify-between gap-3 rounded-lg border p-4 shadow-lg">
          <p className="text-sm font-medium">{t("storage_settings_unsaved_changes")}</p>
          <div className="flex gap-2">
            <Button variant="outline" disabled={interactionUnavailable} onClick={discard}>
              {t("discard_changes")}
            </Button>
            <Button disabled={saveBlocked} aria-busy={saving || undefined} onClick={requestSave}>
              {saving ? t("storage_settings_saving") : t("storage_settings_save")}
            </Button>
          </div>
        </div>
      )}

      <ConfirmDialogControlled
        open={confirmOpen}
        onOpenChange={(next) => {
          if (!saving) setConfirmOpen(next);
        }}
        title={t("storage_settings_confirm_target_title")}
        description={t("storage_settings_confirm_target_description")}
        confirmLabel={t(
          draft.new_write_storage_target === "object_store"
            ? "storage_settings_confirm_object_store"
            : "storage_settings_confirm_postgres"
        )}
        pending={saving}
        onConfirm={() => void save()}
      />
    </>
  );
}
