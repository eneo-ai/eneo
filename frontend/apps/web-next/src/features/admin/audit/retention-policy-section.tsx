"use client";

import { Button } from "@astryxdesign/core/Button";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useId, useRef, useState, type SubmitEvent } from "react";
import { TextInput } from "@/components/astryx/text-input";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { retentionPolicyQueryOptions } from "./audit";

const MIN_DAYS = 1;
const MAX_DAYS = 2555;

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
  const queryClient = useQueryClient();
  const announce = useAnnounce();
  const baseId = useId();
  const headingId = `${baseId}-heading`;
  const editId = `${baseId}-edit`;
  const fieldRef = useRef<HTMLInputElement>(null);
  const Heading = `h${headingLevel}` as const;

  const policy = useQuery(retentionPolicyQueryOptions(browserApi));
  // null while viewing; the field's text while editing.
  const [draft, setDraft] = useState<string | null>(null);
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
            </div>
          ) : (
            <form className="flex flex-wrap items-start gap-3" onSubmit={save} noValidate>
              <TextInput
                ref={fieldRef}
                label={t("audit_retention_period_label")}
                description={t("audit_retention_range")}
                value={draft}
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
                <Button variant="ghost" label={t("cancel")} onClick={cancel} />
              </div>
            </form>
          )
        }
      </QueryStateBoundary>
    </section>
  );
}
