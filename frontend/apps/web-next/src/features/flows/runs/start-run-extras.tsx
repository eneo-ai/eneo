import { Button } from "@astryxdesign/core/Button";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { useMutation, useQuery } from "@tanstack/react-query";
import { History } from "lucide-react";
import { useTranslations } from "use-intl";
import { useEffect, useRef, useState } from "react";
import { TextInput } from "@/components/astryx/text-input";
import { toastApiError } from "@/lib/api/toast";
import { measureAudioSeconds } from "./audio-length";
import { formatSeconds } from "./run-format";
import { refusalText } from "./run-messages";
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
      toastApiError(error, t, {
        title: t("flow_run_more_reuse_failed"),
        message: refusalText(error, t)
      })
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
