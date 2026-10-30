"use client";

import { Button } from "@astryxdesign/core/Button";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { TextArea } from "@astryxdesign/core/TextArea";
import { useMutation } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useTranslations } from "use-intl";
import { useId, useState } from "react";
import { flushSync } from "react-dom";
import { saveBlob } from "@/features/files/signed-file-url";
import { EneoApiError } from "@/lib/api/errors";
import { toast } from "@/lib/toast";
import { focusFirstControl } from "./run-form-fields";
import { flowErrorText, refusalText } from "./run-messages";
import { exportRunEvidence } from "./run-trace-api";
import { EXPORT_REASON_MAX_LENGTH, exportRecovery, rawReasonProblem } from "./run-trace-rules";
import type { EvidenceAccess } from "./runs-api";

type Request = { detail: "redacted" } | { detail: "raw"; reason: string };

/**
 * Exports the run's evidence as the core's JSON file: the redacted export
 * for support and review, and the full export, which needs the person's
 * own reason (the core logs it). Each is offered only when the run detail's
 * `evidence_access` says the core would allow it (the flow's export switch
 * and the classification-3 rule included); otherwise the catalog says why.
 * A refusal says why and, for an export too large to make, where to look
 * instead.
 */
export function RunEvidenceExport({
  flowId,
  runId,
  access
}: {
  flowId: string;
  runId: string;
  access: EvidenceAccess;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const reasonId = useId();
  const [rawOpen, setRawOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [reasonProblem, setReasonProblem] = useState<string | null>(null);

  const download = useMutation({
    mutationFn: (request: Request) => exportRunEvidence(flowId, runId, request),
    onSuccess: ({ blob, filename }) => {
      saveBlob(blob, filename);
      announce(t("flow_run_extras_export_done"));
    },
    onError: (error, request) => {
      if (
        request.detail === "raw" &&
        error instanceof EneoApiError &&
        error.reason === "flow_evidence_export_reason_required"
      ) {
        flushSync(() => setReasonProblem(refusalText(error, t)));
        focusFirstControl(reasonId);
        return;
      }
      const recovery = exportRecovery(error);
      const traceId = error instanceof EneoApiError ? error.traceId : undefined;
      toast.error(t("flow_run_extras_export_failed"), {
        description: [
          refusalText(error, t),
          recovery === "trace" ? t("flow_run_extras_export_recovery_trace") : null,
          recovery === "provider_calls" ? t("flow_run_extras_export_recovery_calls") : null,
          traceId ? `Trace ID: ${traceId}` : null
        ]
          .filter(Boolean)
          .join(" ")
      });
    }
  });

  const refusal = (code: string | null | undefined) =>
    code === "flow_run_evidence_export_disabled"
      ? t("flow_run_extras_export_off")
      : (flowErrorText(code, t) ?? t("flow_run_journey_export_refused"));

  if (!access.can_export_redacted && !access.can_export_raw) {
    return (
      <p className="text-ax-text-secondary text-sm">
        {refusal(access.redacted_export_refusal_code)}
      </p>
    );
  }

  const pending = download.isPending ? download.variables.detail : null;

  return (
    <div className="flex flex-col gap-3">
      {!access.can_export_redacted ? (
        <p className="text-ax-text-secondary text-sm">
          {refusal(access.redacted_export_refusal_code)}
        </p>
      ) : (
        <div className="flex flex-col items-start gap-2">
          <p className="text-ax-text-secondary text-sm">
            {t("flow_run_extras_export_redacted_hint")}
          </p>
          <Button
            label={t("flow_run_extras_export_redacted")}
            icon={<Download aria-hidden="true" />}
            isLoading={pending === "redacted"}
            isInterruptible
            onClick={() => {
              if (!download.isPending) download.mutate({ detail: "redacted" });
            }}
          />
        </div>
      )}
      {!access.can_export_raw ? (
        <p className="text-ax-text-secondary text-sm">{refusal(access.raw_export_refusal_code)}</p>
      ) : (
        <Collapsible
          isOpen={rawOpen}
          onOpenChange={setRawOpen}
          chevronPosition="start"
          trigger={
            <span className="text-sm font-medium">{t("flow_run_extras_export_raw_heading")}</span>
          }
        >
          {rawOpen ? (
            <div id={reasonId} className="flex flex-col items-start gap-2 pt-2">
              <TextArea
                label={t("flow_run_extras_export_raw_reason")}
                description={t("flow_run_extras_export_raw_hint")}
                value={reason}
                onChange={(next) => {
                  setReason(next);
                  setReasonProblem(null);
                }}
                rows={2}
                maxLength={EXPORT_REASON_MAX_LENGTH}
                status={reasonProblem ? { type: "error", message: reasonProblem } : undefined}
                isRequired
                width="100%"
              />
              <Button
                label={t("flow_run_extras_export_raw")}
                icon={<Download aria-hidden="true" />}
                isLoading={pending === "raw"}
                isInterruptible
                onClick={() => {
                  if (download.isPending) return;
                  const problem = rawReasonProblem(reason);
                  if (problem) {
                    flushSync(() =>
                      setReasonProblem(
                        problem === "required"
                          ? t("flow_run_extras_export_raw_reason_required")
                          : t("flow_run_extras_export_raw_reason_too_long", {
                              max: EXPORT_REASON_MAX_LENGTH
                            })
                      )
                    );
                    focusFirstControl(reasonId);
                    return;
                  }
                  download.mutate({ detail: "raw", reason });
                }}
              />
            </div>
          ) : null}
        </Collapsible>
      )}
    </div>
  );
}
