"use client";

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
 * apply. Its heading takes focus when the step opens, so a screen reader
 * reads from there.
 */
export function StartRunSummary({
  summary,
  headingRef,
  notices
}: {
  summary: StartSummary;
  headingRef: Ref<HTMLHeadingElement>;
  notices: ReactNode;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h3
          id={headingId}
          ref={headingRef}
          tabIndex={-1}
          className="text-ax-text focus-visible:outline-ring m-0 text-base font-semibold outline-none focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          {t("flow_runs_summary_title")}
        </h3>
        <p className="text-ax-text-secondary m-0 text-sm">{t("flow_runs_summary_ready")}</p>
      </div>
      {notices}
      {summaryIsEmpty(summary) ? (
        <p className="text-ax-text-secondary m-0 text-sm">{t("flow_runs_summary_empty")}</p>
      ) : (
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
