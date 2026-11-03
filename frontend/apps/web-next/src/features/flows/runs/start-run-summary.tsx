import { Banner } from "@astryxdesign/core/Banner";
import { MetadataList, MetadataListItem } from "@astryxdesign/core/MetadataList";
import { useLocale, useTranslations } from "use-intl";
import { useId, type ReactNode, type Ref } from "react";
import { formatBytes } from "@/lib/format";
import { fieldLabel } from "./run-contract";
import { inputLabel } from "./run-file-inputs";
import { summaryIsEmpty, type StartSummary } from "./start-run-checks";

/**
 * The start dialog's last step: what the run is sent (its name, the fields
 * given a value, the free text and the files), with the notices that still
 * apply. With no input it says so: a warning when the flow takes input (the
 * run can still start), else that all is ready. Its heading takes focus when
 * the step opens, so a screen reader reads from there.
 */
export function StartRunSummary({
  summary,
  takesInput,
  headingRef,
  notices
}: {
  summary: StartSummary;
  /** Whether the flow reads anything given at the start. */
  takesInput: boolean;
  headingRef: Ref<HTMLHeadingElement>;
  notices: ReactNode;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const headingId = useId();
  // The run's name is no material for it.
  const filled = summary.fields.length > 0 || summary.freeText !== null || summary.files.length > 0;
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4">
      <h3
        id={headingId}
        ref={headingRef}
        tabIndex={-1}
        className="text-ax-text focus-visible:outline-ring m-0 text-base font-semibold outline-none focus-visible:outline-2 focus-visible:outline-offset-2"
      >
        {t("flow_runs_summary_title")}
      </h3>
      {filled ? null : (
        <Banner
          status={takesInput ? "warning" : "success"}
          title={t(takesInput ? "flow_runs_start_no_input_title" : "flow_runs_start_ready_title")}
          description={takesInput ? t("flow_runs_start_no_input_body") : undefined}
          collapsible={false}
        />
      )}
      {notices}
      {summaryIsEmpty(summary) ? null : (
        <MetadataList label={{ position: "top" }}>
          {summary.runLabel ? (
            <MetadataListItem label={t("flow_run_extras_run_label")}>
              <span className="break-words">{summary.runLabel}</span>
            </MetadataListItem>
          ) : null}
          {summary.fields.map(({ field, value }) => (
            <MetadataListItem key={field.name} label={fieldLabel(field)}>
              <span className="break-words">{value}</span>
            </MetadataListItem>
          ))}
          {summary.freeText ? (
            <MetadataListItem label={t("flow_runs_free_text")}>
              <span className="break-words whitespace-pre-wrap">{summary.freeText}</span>
            </MetadataListItem>
          ) : null}
          {summary.files.map(({ input, files }) => (
            <MetadataListItem key={input.step_id} label={inputLabel(input, t)}>
              <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
                {files.map((file) => (
                  <li key={file.key} className="flex flex-wrap items-baseline gap-x-2">
                    <span className="min-w-0 break-words">{file.name}</span>
                    <span className="text-ax-text-secondary text-xs tabular-nums">
                      {formatBytes(file.size, locale)}
                    </span>
                  </li>
                ))}
              </ul>
            </MetadataListItem>
          ))}
        </MetadataList>
      )}
    </section>
  );
}
