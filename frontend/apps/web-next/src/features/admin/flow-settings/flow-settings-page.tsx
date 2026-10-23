"use client";

import { Banner } from "@astryxdesign/core/Banner";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Button } from "@astryxdesign/core/Button";
import { Link } from "@astryxdesign/core/Link";
import { Text } from "@astryxdesign/core/Text";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
import { flushSync } from "react-dom";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { PageHeader } from "@/components/composites/page-header";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { useFieldFocus } from "@/features/admin/models/provider-form-fields";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { useLeaveConfirmation } from "@/lib/hooks/use-leave-confirmation";
import {
  buildPatches,
  DOCUMENT_RENDER_KEYS,
  dirtyKeys,
  draftFrom,
  fieldBounds,
  firstProblem,
  FLOW_SETTINGS_KEY,
  flowSettingsQueryOptions,
  flowSettingsWriter,
  rebaseDraft,
  refusalField,
  saveFlowSettings,
  validateDraft,
  type FieldKey,
  type FlowSettings,
  type FlowSettingsDraft,
  type FlowSettingsPatches,
  type FlowSettingsSection,
  type NumberKey
} from "./flow-settings";
import type { FieldKit } from "./flow-settings-fields";
import { problemMessage, refusalMessage } from "./flow-settings-format";
import {
  AUTHORING_CHAT_MODEL_FIELD_ID,
  AuthoringChatSection,
  DocumentSection,
  EvidenceTextSection,
  ExportSection,
  MappedSection,
  RunLimitSection,
  TimeoutSection,
  UploadSections
} from "./flow-settings-sections";

// Audit log entries for tenant settings, which every save here writes.
const AUDIT_HREF = "/admin/audit-logs?actions=tenant_settings_updated";

export function FlowSettingsPage() {
  const t = useTranslations();
  const settings = useQuery(flowSettingsQueryOptions(browserApi));
  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-6">
      <PageHeader title={t("flow_admin_title")} description={t("flow_admin_description")} />
      <QueryStateBoundary query={settings} rows={6}>
        {(initial) => <FlowSettingsEditor initial={initial} />}
      </QueryStateBoundary>
    </div>
  );
}

type Busy = "save" | "capacity" | "restore";
type Refusal = { field: FieldKey | null; message: string; partial: boolean };
type Status = "saved" | "unchanged" | null;

function FlowSettingsEditor({ initial }: { initial: FlowSettings }) {
  const t = useTranslations();
  const locale = useLocale();
  const queryClient = useQueryClient();
  const announce = useAnnounce();
  const focus = useFieldFocus();
  const [settings, setSettings] = useState(initial);
  const [draft, setDraft] = useState<FlowSettingsDraft>(() => draftFrom(initial));
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState<Busy | null>(null);
  const [refusal, setRefusal] = useState<Refusal | null>(null);
  const [status, setStatus] = useState<Status>(null);

  const baseline = draftFrom(settings);
  const bounds = fieldBounds(settings);
  const dirty = dirtyKeys(draft, baseline);
  const problems = submitted ? validateDraft(draft, baseline, settings) : {};
  const leaving = useLeaveConfirmation(dirty.length > 0);

  function problem(key: FieldKey): string | null {
    const found = problems[key];
    if (found && key in bounds) return problemMessage(found, bounds[key as NumberKey], t, locale);
    return refusal?.field === key ? refusal.message : null;
  }

  function set<Key extends FieldKey>(key: Key, value: FlowSettingsDraft[Key]) {
    setDraft((current) => ({ ...current, [key]: value }));
    setStatus(null);
    if (refusal?.field === key) setRefusal({ ...refusal, field: null });
  }

  /** Focus a field; the model picker's trigger is a button, not an input. */
  function focusField(key: FieldKey) {
    if (focus.focus(key)) return;
    if (key === "completion_model_id")
      document.getElementById(AUTHORING_CHAT_MODEL_FIELD_ID)?.focus();
  }

  const kit: FieldKit = {
    draft,
    settings,
    bounds,
    disabled: busy !== null,
    problem,
    set,
    fieldRef: focus.ref
  };
  const changedOrWrong = (keys: readonly FieldKey[]) =>
    keys.some((key) => dirty.includes(key) || problem(key) !== null);

  /** Adopts what the server answered for some sections; the other drafts stay. */
  function adopt(next: FlowSettings, sections: readonly FlowSettingsSection[]) {
    setSettings(next);
    setDraft((current) => rebaseDraft(current, next, sections));
    queryClient.setQueryData(FLOW_SETTINGS_KEY, next);
  }

  // Save is never disabled: a problem shows at its field, which takes focus;
  // busy, it keeps focus and a second press is ignored.
  function save() {
    if (busy) return;
    const found = validateDraft(draft, baseline, settings);
    const first = firstProblem(found);
    if (first) {
      // Rendered before focus moves, so the field is read with its problem.
      flushSync(() => {
        setSubmitted(true);
        setStatus(null);
      });
      focus.focus(first);
      return;
    }
    const patches = buildPatches(draft, baseline);
    if (Object.keys(patches).length === 0) {
      setStatus("unchanged");
      announce(t("form_nothing_to_save"));
      return;
    }
    void persist(patches);
  }

  async function persist(patches: FlowSettingsPatches) {
    setBusy("save");
    setRefusal(null);
    setStatus(null);
    const outcome = await saveFlowSettings(flowSettingsWriter(browserApi), patches);
    const next = { ...settings, ...outcome.saved };
    const savedSections = Object.keys(outcome.saved) as FlowSettingsSection[];
    if (!outcome.failure) {
      adopt(next, savedSections);
      setSubmitted(false);
      setStatus("saved");
      setBusy(null);
      announce(t("flow_admin_saved"));
      return;
    }
    const { error } = outcome.failure;
    const field = refusalField(error);
    flushSync(() => {
      adopt(next, savedSections);
      setBusy(null);
      setRefusal({ field, message: refusalMessage(error, t), partial: savedSections.length > 0 });
    });
    if (field) focusField(field);
  }

  async function runAction<Section extends FlowSettingsSection>(
    kind: Exclude<Busy, "save">,
    request: () => Promise<FlowSettings[Section]>,
    section: Section,
    field: FieldKey,
    done: string
  ) {
    if (busy) return;
    setBusy(kind);
    try {
      const answer = await request();
      // The button goes away with the state it changed: focus moves to the
      // field the action set, after it has rendered.
      flushSync(() => {
        const next: FlowSettings = { ...settings, [section]: answer };
        setSettings(next);
        setDraft((current) => ({ ...current, [field]: draftFrom(next)[field] }));
        queryClient.setQueryData(FLOW_SETTINGS_KEY, next);
        setBusy(null);
      });
      announce(done);
      if (!focus.focus(field)) focus.focus("mapped-enabled");
    } catch (error) {
      setBusy(null);
      toastApiError(error, t);
    }
  }

  function followServerCapacity() {
    void runAction(
      "capacity",
      () =>
        unwrap(
          browserApi.PATCH("/api/v1/settings/flow-runtime-policy", {
            body: { max_concurrent_runs: null }
          })
        ),
      "runtime",
      "max_concurrent_runs",
      t("flow_admin_use_capacity_done")
    );
  }

  function restoreMappedDefault() {
    void runAction(
      "restore",
      () =>
        unwrap(
          browserApi.PATCH("/api/v1/settings/flow-mapped-execution-policy", {
            body: { restore_max_provider_calls_default: true }
          })
        ),
      "mapped",
      "max_provider_calls_per_mapped_step",
      t("flow_admin_mapped_restored")
    );
  }

  function discard() {
    setDraft(baseline);
    setSubmitted(false);
    setRefusal(null);
    setStatus(null);
  }

  const statusText =
    dirty.length > 0
      ? t("flow_admin_unsaved", { count: dirty.length })
      : status === "saved"
        ? t("flow_admin_saved")
        : status === "unchanged"
          ? t("form_nothing_to_save")
          : t("flow_admin_no_changes");

  return (
    // Focused fields stay clear of the sticky save bar (WCAG 2.4.11).
    <div className="flex flex-col gap-6 [&_input]:scroll-mb-32">
      <Text type="supporting" size="sm" as="p" display="block" className="m-0">
        <Link href={AUDIT_HREF} hasUnderline>
          {t("flow_admin_audit_link")}
        </Link>
      </Text>
      <UploadSections kit={kit} />
      <RunLimitSection
        kit={kit}
        busy={busy === "capacity"}
        onFollowCapacity={followServerCapacity}
      />
      <TimeoutSection
        kit={kit}
        isPinnedOpen={changedOrWrong(["default_step_timeout_seconds", "max_step_timeout_seconds"])}
      />
      <MappedSection
        kit={kit}
        isDirty={dirty.includes("max_provider_calls_per_mapped_step")}
        busy={busy === "restore"}
        onRestoreDefault={restoreMappedDefault}
      />
      <EvidenceTextSection kit={kit} />
      <DocumentSection kit={kit} isPinnedOpen={changedOrWrong(DOCUMENT_RENDER_KEYS)} />
      <ExportSection kit={kit} />
      <AuthoringChatSection kit={kit} />

      <div className="bg-ax-card border-ax-border rounded-ax-container shadow-ax-high sticky bottom-4 z-20 flex flex-col gap-3 border p-4">
        {refusal ? (
          <Banner
            role="alert"
            status="error"
            title={t("flow_admin_save_failed")}
            description={
              refusal.partial
                ? `${refusal.message} ${t("flow_admin_save_partial")}`
                : refusal.message
            }
          />
        ) : null}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Text size="sm" weight="medium" as="p" display="block" className="m-0">
            {statusText}
          </Text>
          <div className="flex gap-2">
            <Button
              label={t("discard_changes")}
              isDisabled={dirty.length === 0 || busy !== null}
              onClick={discard}
            />
            <Button
              label={busy === "save" ? t("flow_admin_saving") : t("flow_admin_save")}
              variant="primary"
              isLoading={busy === "save"}
              isInterruptible
              onClick={save}
            />
          </div>
        </div>
      </div>

      <ConfirmDialogControlled
        open={leaving.pendingHref !== null}
        onOpenChange={(open) => {
          if (!open) leaving.stay();
        }}
        title={t("flow_admin_leave_title")}
        description={t("flow_admin_leave_description")}
        confirmLabel={t("flow_admin_leave_confirm")}
        onConfirm={leaving.leave}
      />
    </div>
  );
}
