"use client";

import { Button } from "@astryxdesign/core/Button";
import { Link } from "@astryxdesign/core/Link";
import { MetadataList, MetadataListItem } from "@astryxdesign/core/MetadataList";
import { Text } from "@astryxdesign/core/Text";
import { useQuery } from "@tanstack/react-query";
import { useLocale, useTranslations } from "use-intl";
import { useState } from "react";
import { ModelSelector } from "@/components/ai-elements/model-selector";
import { Banner } from "@astryxdesign/core/Banner";
import { Switch } from "@astryxdesign/core/Switch";
import { useAppContext } from "@/components/providers/app-context";
import { adminModelsQueryOptions } from "@/features/admin/models/models";
import { browserApi } from "@/lib/api/browser";
import { formatBytes } from "@/lib/format";
import {
  DOCUMENT_RENDER_KEYS,
  MAX_AUDIO_FILES_PER_RUN,
  MAX_FILES_PER_RUN,
  RAG_EVIDENCE_KEYS,
  type FlagKey
} from "./flow-settings";
import {
  AdvancedSettings,
  SettingNumberField,
  SettingsSection,
  useLimitDescription,
  type FieldKit
} from "./flow-settings-fields";
import { audioRunningTime, formatNumber, formatSeconds } from "./flow-settings-format";

/** What a mapped step's call ceiling suggests when new per-file steps are switched on. */
const MAPPED_CALLS_SUGGESTION = 100;

export function UploadSections({ kit }: { kit: FieldKit }) {
  const t = useTranslations();
  const locale = useLocale();
  const { inputLimits } = kit.settings;
  const ceilingMinutes = Math.floor(inputLimits.audio_max_duration_ceiling_seconds / 60);
  const duration = kit.draft.audio_max_duration_seconds;

  return (
    <>
      <SettingsSection
        id="flow-files"
        title={t("flow_admin_files_group")}
        description={t("flow_admin_files_group_description")}
      >
        <StorageLimit
          label={t("flow_admin_file_size_label")}
          value={formatBytes(inputLimits.file_max_size_bytes, locale)}
        />
        <SettingNumberField
          kit={kit}
          field="max_files_per_run"
          label={t("flow_admin_max_files_label")}
          description={t("flow_admin_max_files_description", {
            max: formatNumber(MAX_FILES_PER_RUN, locale)
          })}
          placeholder={t("flow_admin_deployment_default")}
        />
      </SettingsSection>

      <SettingsSection
        id="flow-audio"
        title={t("flow_admin_audio_group")}
        description={t("flow_admin_audio_group_description")}
      >
        <StorageLimit
          label={t("flow_admin_audio_size_label")}
          value={formatBytes(inputLimits.audio_max_size_bytes, locale)}
          note={audioRunningTime(inputLimits.audio_max_size_bytes, t)}
        />
        <div className="grid gap-5 md:grid-cols-2">
          <SettingNumberField
            kit={kit}
            field="audio_max_files_per_run"
            label={t("flow_admin_audio_max_files_label")}
            description={`${t("flow_admin_audio_max_files_description", {
              max: formatNumber(MAX_AUDIO_FILES_PER_RUN, locale)
            })} ${t("flow_admin_empty_restores_default")}`}
            placeholder={t("flow_admin_deployment_default")}
          />
          <SettingNumberField
            kit={kit}
            field="audio_max_duration_seconds"
            label={t("flow_admin_audio_duration_label")}
            description={[
              t("flow_admin_audio_duration_description", { ceiling: ceilingMinutes }),
              duration !== null && duration >= 3600
                ? t("flow_admin_duration_equivalent", { duration: formatSeconds(duration, t) })
                : null,
              t("flow_admin_empty_restores_default")
            ]
              .filter(Boolean)
              .join(" ")}
            units={t("flow_admin_unit_minutes")}
            placeholder={t("flow_admin_deployment_default")}
          />
        </div>
      </SettingsSection>
    </>
  );
}

/** A size every flow shares, read here and changed under File storage. */
function StorageLimit({ label, value, note }: { label: string; value: string; note?: string }) {
  const t = useTranslations();
  return (
    <div className="flex flex-col gap-1">
      <MetadataList label={{ position: "start", width: 160 }}>
        <MetadataListItem label={label}>
          <span className="flex flex-col">
            <span className="tabular-nums">{value}</span>
            {note ? (
              <Text type="supporting" size="sm">
                {note}
              </Text>
            ) : null}
          </span>
        </MetadataListItem>
      </MetadataList>
      <Text type="supporting" size="sm" as="p" display="block" className="m-0">
        {t("flow_admin_size_from_storage")}{" "}
        <Link href="/admin/storage" hasUnderline>
          {t("flow_admin_manage_storage")}
        </Link>
      </Text>
    </div>
  );
}

export function RunLimitSection({
  kit,
  busy,
  onFollowCapacity
}: {
  kit: FieldKit;
  /** "Använd serverns kapacitet" is running. */
  busy: boolean;
  onFollowCapacity: () => void;
}) {
  const t = useTranslations();
  const { runtime } = kit.settings;
  const capacity = runtime.max_concurrent_runs_capacity;
  const saved = runtime.max_concurrent_runs_override ?? null;
  const noCapacity = capacity < 1;
  const description = noCapacity
    ? t("flow_admin_max_runs_no_capacity")
    : saved !== null && saved > capacity
      ? `${t("flow_admin_max_runs_description", { capacity })} ${t("flow_admin_max_runs_clamped", {
          limit: capacity,
          saved
        })}`
      : t("flow_admin_max_runs_description", { capacity });

  return (
    <SettingsSection
      id="flow-runs"
      title={t("flow_admin_runs_group")}
      description={t("flow_admin_runs_group_description")}
    >
      <SettingNumberField
        kit={kit}
        field="max_concurrent_runs"
        label={t("flow_admin_max_runs_label")}
        description={description}
        disabledMessage={noCapacity ? t("flow_admin_max_runs_no_capacity") : undefined}
      />
      {saved !== null ? (
        <div>
          {/* Sends null whatever the field shows: a value capacity limits looks equal to it. */}
          <Button
            label={t("flow_admin_use_capacity")}
            size="sm"
            isLoading={busy}
            isInterruptible
            onClick={onFollowCapacity}
          />
        </div>
      ) : null}
    </SettingsSection>
  );
}

export function TimeoutSection({ kit, isPinnedOpen }: { kit: FieldKit; isPinnedOpen: boolean }) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const ceiling = kit.settings.runtime.hard_ceiling_seconds;
  const normal = kit.draft.default_step_timeout_seconds;
  const longest = kit.draft.max_step_timeout_seconds;
  const describe = (base: string, value: number | null) =>
    [
      base,
      value !== null && value >= 60
        ? t("flow_admin_duration_equivalent", { duration: formatSeconds(value, t) })
        : null,
      t("flow_admin_empty_restores_default")
    ]
      .filter(Boolean)
      .join(" ");

  return (
    <SettingsSection
      id="flow-timeouts"
      title={t("flow_admin_timeouts_group")}
      description={t("flow_admin_timeouts_group_description")}
    >
      <AdvancedSettings
        title={t("flow_admin_timeouts_trigger")}
        summary={t("flow_admin_timeouts_summary", {
          normal: formatSeconds(normal ?? ceiling, t),
          maximum: formatSeconds(longest ?? ceiling, t)
        })}
        isOpen={open}
        isPinnedOpen={isPinnedOpen}
        onOpenChange={setOpen}
      >
        <SettingNumberField
          kit={kit}
          field="default_step_timeout_seconds"
          label={t("flow_admin_default_timeout_label")}
          description={describe(t("flow_admin_default_timeout_description"), normal)}
          units={t("flow_admin_unit_seconds")}
          placeholder={t("flow_admin_deployment_default")}
        />
        <SettingNumberField
          kit={kit}
          field="max_step_timeout_seconds"
          label={t("flow_admin_max_timeout_label")}
          description={describe(
            t("flow_admin_max_timeout_description", { ceiling: formatSeconds(ceiling, t) }),
            longest
          )}
          units={t("flow_admin_unit_seconds")}
          placeholder={t("flow_admin_deployment_default")}
        />
      </AdvancedSettings>
    </SettingsSection>
  );
}

export function MappedSection({
  kit,
  isDirty,
  busy,
  onRestoreDefault
}: {
  kit: FieldKit;
  /** The call ceiling has an unsaved change. */
  isDirty: boolean;
  /** "Återställ till driftmiljöns standard" is running. */
  busy: boolean;
  onRestoreDefault: () => void;
}) {
  const t = useTranslations();
  const { mapped } = kit.settings;
  const calls = kit.draft.max_provider_calls_per_mapped_step;
  const deploymentDefault = mapped.deployment_default_max_provider_calls ?? null;
  const suggestion =
    mapped.max_provider_calls_per_mapped_step ?? deploymentDefault ?? MAPPED_CALLS_SUGGESTION;

  return (
    <SettingsSection
      id="flow-mapped"
      title={t("flow_admin_mapped_group")}
      description={t("flow_admin_mapped_group_description")}
    >
      {mapped.max_provider_calls_source === "invalid" ? (
        <Banner
          status="error"
          title={t("flow_admin_mapped_invalid_title")}
          description={t("flow_admin_mapped_invalid")}
        />
      ) : null}
      <Switch
        ref={kit.fieldRef("mapped-enabled")}
        label={t("flow_admin_mapped_enable_label")}
        description={t("flow_admin_mapped_enable_description")}
        value={calls !== null}
        isDisabled={kit.disabled}
        onChange={(on) => kit.set("max_provider_calls_per_mapped_step", on ? suggestion : null)}
      />
      {calls !== null ? (
        <SettingNumberField
          kit={kit}
          field="max_provider_calls_per_mapped_step"
          label={t("flow_admin_mapped_calls_label")}
          description={`${t("flow_admin_mapped_calls_description")} ${t(
            "flow_admin_mapped_calls_files",
            { calls, files: calls - 1 }
          )}`}
          units={t("flow_admin_unit_calls")}
        />
      ) : (
        <Text type="supporting" size="sm" as="p" display="block" className="m-0">
          {t("flow_admin_mapped_off_status")}
        </Text>
      )}
      {mapped.max_provider_calls_source === "deployment_default" ? (
        isDirty ? null : (
          <Text type="supporting" size="sm" as="p" display="block" className="m-0">
            {t("flow_admin_mapped_inherited")}
          </Text>
        )
      ) : (
        <div>
          <Button
            label={
              deploymentDefault !== null
                ? t("flow_admin_mapped_restore_value", { value: deploymentDefault })
                : t("flow_admin_mapped_restore")
            }
            variant="ghost"
            size="sm"
            isLoading={busy}
            isInterruptible
            onClick={onRestoreDefault}
          />
        </div>
      )}
      <SettingNumberField
        kit={kit}
        field="max_estimated_input_tokens_per_mapped_step"
        label={t("flow_admin_mapped_tokens_label")}
        description={t("flow_admin_mapped_tokens_description")}
        units={t("flow_admin_unit_tokens")}
      />
    </SettingsSection>
  );
}

const EVIDENCE_TEXT_FIELDS = {
  max_sources_with_recorded_passages: {
    label: "flow_admin_evidence_sources_label",
    description: "flow_admin_evidence_sources_description"
  },
  max_recorded_passages_per_source: {
    label: "flow_admin_evidence_passages_label",
    description: "flow_admin_evidence_passages_description"
  },
  max_recorded_passage_bytes: {
    label: "flow_admin_evidence_passage_size_label",
    description: "flow_admin_evidence_passage_size_description"
  },
  max_recorded_passage_bytes_per_step: {
    label: "flow_admin_evidence_step_size_label",
    description: "flow_admin_evidence_step_size_description"
  },
  max_recorded_passage_bytes_per_run_view: {
    label: "flow_admin_evidence_run_view_label",
    description: "flow_admin_evidence_run_view_description"
  }
} as const satisfies Record<(typeof RAG_EVIDENCE_KEYS)[number], unknown>;

export function EvidenceTextSection({ kit }: { kit: FieldKit }) {
  const t = useTranslations();
  const locale = useLocale();
  const { draft } = kit;
  const sources = draft.max_sources_with_recorded_passages;
  const passages = draft.max_recorded_passages_per_source;
  const total = draft.max_recorded_passage_bytes_per_step;

  return (
    <SettingsSection
      id="flow-evidence-text"
      title={t("flow_admin_evidence_group")}
      description={t("flow_admin_evidence_group_description")}
    >
      <div className="grid gap-5 md:grid-cols-2">
        {RAG_EVIDENCE_KEYS.map((field) => {
          const bounds = kit.bounds[field];
          const max =
            bounds.max === null
              ? ""
              : bounds.scale === 1
                ? formatNumber(bounds.max, locale)
                : formatBytes(bounds.max, locale);
          return (
            <SettingNumberField
              key={field}
              kit={kit}
              field={field}
              label={t(EVIDENCE_TEXT_FIELDS[field].label)}
              description={`${t(EVIDENCE_TEXT_FIELDS[field].description, { max })} ${t(
                "flow_admin_empty_restores_default"
              )}`}
              units={bounds.scale === 1 ? undefined : t("flow_admin_unit_kb")}
              placeholder={t("flow_admin_deployment_default")}
            />
          );
        })}
      </div>
      <Text type="supporting" size="sm" as="p" display="block" className="m-0">
        {sources === null || passages === null || total === null
          ? t("flow_admin_evidence_summary_pending")
          : t("flow_admin_evidence_summary", {
              sources: formatNumber(sources, locale),
              passages: formatNumber(passages, locale),
              total: formatBytes(total, locale)
            })}
      </Text>
    </SettingsSection>
  );
}

export function DocumentSection({ kit, isPinnedOpen }: { kit: FieldKit; isPinnedOpen: boolean }) {
  const t = useTranslations();
  const locale = useLocale();
  const limitDescription = useLimitDescription();
  const [open, setOpen] = useState(false);

  return (
    <SettingsSection
      id="flow-documents"
      title={t("flow_admin_documents_group")}
      description={t("flow_admin_documents_group_description")}
    >
      <AdvancedSettings
        title={t("flow_admin_documents_trigger")}
        summary={t("flow_admin_documents_summary")}
        isOpen={open}
        isPinnedOpen={isPinnedOpen}
        onOpenChange={setOpen}
      >
        {DOCUMENT_RENDER_KEYS.map((field) => (
          <SettingNumberField
            key={field}
            kit={kit}
            field={field}
            label={t(`flow_admin_document_${field}`)}
            description={limitDescription(formatNumber(kit.bounds[field].max ?? 0, locale))}
            placeholder={t("flow_admin_deployment_default")}
          />
        ))}
      </AdvancedSettings>
    </SettingsSection>
  );
}

const EXPORT_SWITCHES: { field: FlagKey; label: string; description?: string }[] = [
  { field: "allow_space_admin_raw_export_class3", label: "flow_admin_export_space_admin" },
  {
    field: "allow_run_owner_raw_export_class3",
    label: "flow_admin_export_run_owner",
    description: "flow_admin_export_run_owner_description"
  },
  { field: "allow_service_key_raw_export_class3", label: "flow_admin_export_service_key" }
];

export function ExportSection({ kit }: { kit: FieldKit }) {
  const t = useTranslations();
  return (
    <SettingsSection
      id="flow-export"
      title={t("flow_admin_export_group")}
      description={t("flow_admin_export_group_description")}
    >
      <fieldset className="flex flex-col gap-4">
        <legend className="sr-only">{t("flow_admin_export_group")}</legend>
        {EXPORT_SWITCHES.map(({ field, label, description }) => (
          <Switch
            key={field}
            ref={kit.fieldRef(field)}
            label={t(label)}
            description={description ? t(description) : undefined}
            value={kit.draft[field]}
            isDisabled={kit.disabled}
            onChange={(on) => kit.set(field, on)}
          />
        ))}
      </fieldset>
    </SettingsSection>
  );
}

/** The trigger's id, so a refused save can move focus to it. */
export const AUTHORING_CHAT_MODEL_FIELD_ID = "flow-setting-completion_model_id";

/**
 * "Modell för flödesassistenten": the organisation's default model for flow
 * chats. The list holds the organisation's enabled models that support
 * tools; the first option leaves each chat on its space's default. A space
 * that does not allow the chosen model keeps its own default, and a person
 * can still choose another model in their chat.
 */
export function AuthoringChatSection({ kit }: { kit: FieldKit }) {
  const t = useTranslations();
  const { tenant } = useAppContext();
  const catalog = useQuery(adminModelsQueryOptions(browserApi));
  const models = (catalog.data?.completion_models ?? []).filter(
    (model) =>
      model.supports_tool_calling &&
      model.is_org_enabled !== false &&
      model.can_access !== false &&
      !model.is_deprecated
  );
  const problem = kit.problem("completion_model_id");

  return (
    <SettingsSection
      id="flow-chat"
      title={t("flow_admin_chat_group")}
      description={t("flow_admin_chat_group_description")}
    >
      {/* Focus moves to the trigger by its id (the page's focusField): the
          picker holds inputs of its own that must not take it. */}
      <div className="max-w-md">
        <ModelSelector
          id={AUTHORING_CHAT_MODEL_FIELD_ID}
          models={models}
          selectedId={kit.draft.completion_model_id}
          onSelect={(id) => kit.set("completion_model_id", id)}
          defaultChoice={{
            label: t("flow_admin_chat_model_space_default"),
            modelId: null,
            isSelected: kit.draft.completion_model_id === null,
            onSelect: () => kit.set("completion_model_id", null)
          }}
          field={{
            label: t("flow_admin_chat_model_label"),
            description: t("flow_admin_chat_model_description")
          }}
          disabled={kit.disabled || catalog.isPending}
          showPricing={tenant.show_model_pricing}
          status={problem ? { type: "error", message: problem } : undefined}
        />
      </div>
    </SettingsSection>
  );
}
