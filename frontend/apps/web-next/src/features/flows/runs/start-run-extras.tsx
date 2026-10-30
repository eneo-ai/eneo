"use client";

import { Button } from "@astryxdesign/core/Button";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { useMutation, useQuery } from "@tanstack/react-query";
import { History } from "lucide-react";
import { useTranslations } from "use-intl";
import { useEffect, useRef, useState } from "react";
import { TextInput } from "@astryxdesign/core/TextInput";
import { StatusLabel, type StatusTone } from "@/components/composites/status-label";
import type { Schema } from "@/lib/api/models";
import { toast } from "@/lib/toast";
import { measureAudioSeconds } from "./audio-length";
import { formatSeconds } from "./run-format";
import { flowErrorText, refusalText } from "./run-messages";
import {
  fitRunLabel,
  RUN_LABEL_MAX_LENGTH,
  reusedInput,
  screenAudioFiles,
  takesReusableInput
} from "./start-run-checks";
import {
  getRunDetail,
  lastOwnRunQueryOptions,
  type RunContract,
  type RuntimeInput
} from "./runs-api";

type TemplateStatus = Schema<"FlowTemplateAssetStatus">;

/**
 * The run's own name: optional, one line, the run page's title. Text past
 * the core's limit is left out, and the field says so.
 */
export function RunLabelField({
  value,
  onChange
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const t = useTranslations();
  const [cut, setCut] = useState(false);
  return (
    <TextInput
      label={t("flow_run_extras_run_label")}
      description={t("flow_run_extras_run_label_hint", { max: RUN_LABEL_MAX_LENGTH })}
      value={value}
      onChange={(next) => {
        const fitted = fitRunLabel(next);
        setCut(fitted.cut);
        onChange(fitted.label);
      }}
      status={
        cut
          ? {
              type: "warning",
              message: t("flow_run_extras_run_label_cut", { max: RUN_LABEL_MAX_LENGTH })
            }
          : undefined
      }
      autoComplete="off"
      isOptional
      width="100%"
    />
  );
}

const TEMPLATE_VIEWS: Record<TemplateStatus, { tone: StatusTone; labelKey: string }> = {
  ready: { tone: "success", labelKey: "flow_run_extras_template_ready" },
  read_only: { tone: "accent", labelKey: "flow_run_extras_template_read_only" },
  needs_action: { tone: "warning", labelKey: "flow_run_extras_template_needs_action" },
  unavailable: { tone: "error", labelKey: "flow_run_extras_template_unavailable" }
};

/**
 * The Word templates the flow's steps fill, each with whether it is ready
 * for this run and, when it is not, the catalog's reason, so the person
 * sees before starting what the flow will produce documents from.
 */
export function TemplateReadiness({
  contract
}: {
  contract: Pick<RunContract, "template_readiness">;
}) {
  const t = useTranslations();
  const items = contract.template_readiness ?? [];
  if (items.length === 0) return null;
  return (
    <section className="flex flex-col gap-1" aria-label={t("flow_run_extras_templates_heading")}>
      <p className="text-ax-text text-sm font-medium">{t("flow_run_extras_templates_heading")}</p>
      <ul className="m-0 flex flex-col p-0">
        {items.map((item) => {
          const view = TEMPLATE_VIEWS[item.status] ?? TEMPLATE_VIEWS.unavailable;
          const reason =
            item.status === "ready"
              ? null
              : (flowErrorText(item.message_code, t) ??
                (item.status === "read_only"
                  ? t("flow_run_extras_template_read_only_hint")
                  : t("flow_run_extras_template_needs_action_hint")));
          return (
            <li
              key={item.step_id}
              className="border-ax-border flex flex-col gap-0.5 border-t py-2 first:border-t-0"
            >
              <span className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-ax-text text-sm break-words">
                  {item.template_name?.trim() || t("flow_run_extras_template_unnamed")}
                </span>
                <StatusLabel status={view.tone} label={t(view.labelKey)} />
              </span>
              {reason ? <span className="text-ax-text-secondary text-xs">{reason}</span> : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/**
 * Checks picked audio against the length one file of its input can hold
 * (`max_duration_seconds`, from the tenant's transcription limits) before
 * uploading, so a file that could never be transcribed is refused at once
 * instead of failing the run. `onRefused` gets the sentence for the input;
 * `then` gets the files to upload. Other inputs pass straight through.
 */
export function useAudioLengthCheck(onRefused: (stepId: string, message: string) => void) {
  const t = useTranslations();
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  return (input: RuntimeInput, files: readonly File[], then: (accepted: File[]) => void) => {
    if (input.input_format !== "audio" || input.max_duration_seconds == null) {
      then([...files]);
      return;
    }
    void screenAudioFiles(input, files, measureAudioSeconds).then(({ accepted, refused }) => {
      // The form closed while the files were read: nothing to upload them for.
      if (!mounted.current) return;
      if (refused.length > 0) {
        onRefused(
          input.step_id,
          refused
            .map((file) =>
              t("flow_run_extras_audio_too_long", {
                name: file.name,
                length: formatSeconds(file.seconds, t),
                max: formatSeconds(file.maxSeconds, t)
              })
            )
            .join(" ")
        );
      }
      if (accepted.length > 0) then(accepted);
    });
  };
}

/**
 * Fills the form from the caller's newest run of this flow: its field values
 * or its free text, read from that run when asked (an audited content read).
 * Offered only when the caller has run the flow and the form has fields or a
 * free text; files are picked again.
 */
export function ReuseLastInput({
  flowId,
  contract,
  onApply
}: {
  flowId: string;
  contract: Pick<RunContract, "form_fields" | "steps_requiring_input">;
  onApply: (input: ReturnType<typeof reusedInput>) => void;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const reusable = takesReusableInput(contract);
  const last = useQuery({ ...lastOwnRunQueryOptions(flowId), enabled: reusable });
  const read = useMutation({
    mutationFn: (runId: string) => getRunDetail(flowId, runId),
    onSuccess: (run) => {
      onApply(reusedInput(contract, run.input_payload_json));
      announce(t("flow_run_more_reuse_done"));
    },
    onError: (error) =>
      toast.error(t("flow_run_more_reuse_failed"), { description: refusalText(error, t) })
  });
  const run = last.data;
  if (!reusable || !run) return null;
  return (
    <div className="flex flex-col items-start gap-1">
      <Button
        label={t("flow_run_more_reuse")}
        icon={<History aria-hidden="true" />}
        size="sm"
        isLoading={read.isPending}
        isInterruptible
        onClick={() => {
          if (!read.isPending) read.mutate(run.id);
        }}
      />
      {(contract.steps_requiring_input ?? []).length > 0 ? (
        <p className="text-ax-text-secondary m-0 text-xs">{t("flow_run_more_reuse_files")}</p>
      ) : null}
    </div>
  );
}
