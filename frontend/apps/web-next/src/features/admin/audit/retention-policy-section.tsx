"use client";

import { Button } from "@astryxdesign/core/Button";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil } from "lucide-react";
import { useFormatter, useTranslations } from "use-intl";
import { useEffect, useId, useRef, useState, type SubmitEvent } from "react";
import { TextInput } from "@/components/astryx/text-input";
import { QuietBanner } from "@/components/astryx/banner";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { useAnnounceChange } from "@/lib/hooks/use-announce-change";
import { retentionPolicyQueryOptions } from "./audit";

const MIN_DAYS = 1;
const MAX_DAYS = 2555;
const PRESETS = [
  { days: 90, key: "audit_preset_3_months" },
  { days: 365, key: "audit_preset_1_year" },
  { days: 730, key: "audit_preset_2_years" },
  { days: 2555, key: "audit_preset_7_years" }
] as const;

function parseDays(value: string): number | null {
  const days = Number(value.trim());
  return Number.isInteger(days) && days >= MIN_DAYS && days <= MAX_DAYS ? days : null;
}

/**
 * The audit-log retention period on the admin settings page: the current
 * value as text with an "Ändra" button that swaps in a field, Save and Cancel.
 * Saving announces the result and returns focus to "Ändra"; a value outside
 * 1–2555 days is reported at the field. Conversation retention lives elsewhere.
 */
export function RetentionPolicySection({ headingLevel = 2 }: { headingLevel?: 2 | 3 }) {
  const t = useTranslations();
  const format = useFormatter();
  const queryClient = useQueryClient();
  const announce = useAnnounce();
  const baseId = useId();
  const headingId = `${baseId}-heading`;
  const editId = `${baseId}-edit`;
  const fieldRef = useRef<HTMLInputElement>(null);
  const Heading = `h${headingLevel}` as const;
  const cutoff = (days: number) => {
    const date = new Date();
    date.setDate(date.getDate() - days);
    return format.dateTime(date, { year: "numeric", month: "long", day: "numeric" });
  };

  const policy = useQuery(retentionPolicyQueryOptions(browserApi));
  // null while viewing; the field's text while editing.
  const [draft, setDraft] = useState<string | null>(null);
  const draftDays = draft === null ? null : parseDays(draft);
  const periodChange =
    draftDays !== null && policy.data && draftDays !== policy.data.retention_days
      ? draftDays < policy.data.retention_days
        ? "shorter"
        : "longer"
      : null;
  useAnnounceChange(
    periodChange
      ? t(
          periodChange === "shorter"
            ? "audit_retention_warning_title"
            : "audit_retention_info_title"
        )
      : null,
    periodChange
  );
  const [problem, setProblem] = useState<string | null>(null);
  // Set by Save and Cancel: once the field is gone, focus goes back to "Ändra".
  const returnFocus = useRef(false);
  useEffect(() => {
    if (draft !== null || !returnFocus.current) return;
    returnFocus.current = false;
    document.getElementById(editId)?.focus();
  }, [draft, editId]);

  const update = useMutation({
    mutationFn: (days: number) =>
      unwrap(
        browserApi.PUT("/api/v1/audit/retention-policy", {
          body: { retention_days: days }
        })
      ),
    onSuccess: (updated) => {
      queryClient.setQueryData(retentionPolicyQueryOptions(browserApi).queryKey, updated);
      returnFocus.current = true;
      setDraft(null);
      announce(t("audit_retention_saved"));
    },
    onError: (error) => toastApiError(error, t)
  });

  function save(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (update.isPending || draft === null) return;
    const days = parseDays(draft);
    if (days === null) {
      setProblem(t("audit_retention_invalid"));
      fieldRef.current?.focus();
      return;
    }
    update.mutate(days);
  }

  function cancel() {
    if (update.isPending) return;
    returnFocus.current = true;
    setDraft(null);
    setProblem(null);
  }

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <Heading id={headingId} className="font-semibold">
          {t("audit_retention_policy")}
        </Heading>
        <p className="text-ax-text-secondary text-sm">{t("audit_retention_description")}</p>
      </div>
      <QueryStateBoundary query={policy} rows={1}>
        {(data) =>
          draft === null ? (
            <div className="flex flex-wrap items-center gap-3">
              <p className="text-sm">
                <span className="font-semibold tabular-nums">
                  {t("audit_retention_current", { days: data.retention_days })}
                </span>
                {data.last_purge_at ? (
                  <span className="text-ax-text-secondary">
                    {" · "}
                    {t("audit_last_purge", { count: data.purge_count })}
                  </span>
                ) : null}
              </p>
              <Button
                id={editId}
                size="sm"
                label={t("change")}
                icon={<Pencil aria-hidden="true" />}
                onClick={() => {
                  setProblem(null);
                  setDraft(String(data.retention_days));
                }}
              />
              <p className="text-ax-text-secondary w-full text-sm">
                {t("audit_retention_cutoff", { date: cutoff(data.retention_days) })}
              </p>
            </div>
          ) : (
            <form className="flex flex-wrap items-start gap-3" onSubmit={save} noValidate>
              <TextInput
                ref={fieldRef}
                label={t("audit_retention_period_label")}
                description={t("audit_retention_range")}
                value={draft}
                isDisabled={update.isPending}
                onChange={(value) => {
                  setDraft(value);
                  setProblem(null);
                }}
                status={problem ? { type: "error", message: problem } : undefined}
                statusVariant="detached"
                width="14rem"
              />
              {/* Aligned with the field's control, below its label. */}
              <div className="flex gap-2 pt-6">
                {/* Busy, Save stays enabled so it keeps focus; a second press is ignored. */}
                <Button
                  type="submit"
                  variant="primary"
                  label={update.isPending ? t("audit_retention_saving") : t("save")}
                  isLoading={update.isPending}
                  isInterruptible
                />
                <Button
                  variant="ghost"
                  label={t("cancel")}
                  aria-disabled={update.isPending}
                  onClick={cancel}
                />
              </div>
              <div className="flex w-full flex-wrap gap-2">
                {PRESETS.map(({ days, key }) => (
                  <Button
                    key={days}
                    type="button"
                    size="sm"
                    label={t(key)}
                    aria-pressed={draftDays === days}
                    aria-disabled={update.isPending}
                    onClick={() => {
                      if (update.isPending) return;
                      setDraft(String(days));
                      setProblem(null);
                    }}
                  />
                ))}
              </div>
              {draftDays !== null && draftDays !== data.retention_days ? (
                <div className="w-full">
                  <QuietBanner
                    status={draftDays < data.retention_days ? "warning" : "info"}
                    title={t(
                      draftDays < data.retention_days
                        ? "audit_retention_warning_title"
                        : "audit_retention_info_title"
                    )}
                    description={
                      draftDays < data.retention_days
                        ? t("audit_retention_warning_desc", { date: cutoff(draftDays) })
                        : t("audit_retention_info_desc")
                    }
                  />
                </div>
              ) : null}
            </form>
          )
        }
      </QueryStateBoundary>
    </section>
  );
}
