"use client";

import { Collapsible } from "@astryxdesign/core/Collapsible";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
import { formatCount } from "./run-format";
import { JsonValue } from "./run-json";
import {
  rejectedOutput,
  runtimeInputSummary,
  sectionReading,
  templateProvenance
} from "./run-step-facts";
import type { RunStep } from "./runs-api";

const INPUT_FORMATS: ReadonlySet<string> = new Set(["audio", "document", "file"]);

/** How a step read long material: in one go, or part by part and where each part sat. */
export function StepSectionReading({ payload }: { payload: RunStep["output_payload_json"] }) {
  const t = useTranslations();
  const reading = sectionReading(payload);
  if (!reading) return null;
  const count = reading.ranges.length;
  return (
    <div className="flex flex-col gap-0.5">
      <p className="text-ax-text-secondary m-0 text-sm">
        {count === 1
          ? t("flow_run_sections_read_one")
          : t("flow_run_journey_sections_read", { count })}
      </p>
      {count > 1 ? (
        <p className="text-ax-text-secondary m-0 text-xs">
          {t("flow_run_sections_positions")}{" "}
          {reading.ranges
            .map((range, index) =>
              t("flow_run_section_position", { index: index + 1, from: range.from, to: range.to })
            )
            .join(", ")}
        </p>
      ) : null}
    </div>
  );
}

/**
 * The answer a step gave that broke its format, decoded, as the diagnostic
 * it is: closed until asked for, since the step's error already says why.
 */
export function StepRejectedOutput({ payload }: { payload: RunStep["output_payload_json"] }) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const rejected = rejectedOutput(payload);
  if (!rejected) return null;
  return (
    <Collapsible
      isOpen={open}
      onOpenChange={setOpen}
      chevronPosition="start"
      trigger={<span className="text-sm font-medium">{t("flow_run_rejected_output_title")}</span>}
    >
      {open ? (
        <div className="pt-2">
          {typeof rejected.value === "string" ? (
            <pre className="bg-ax-sunken rounded-ax-inner text-ax-text max-h-96 overflow-auto p-2 text-xs break-words whitespace-pre-wrap">
              {rejected.value}
            </pre>
          ) : (
            <JsonValue value={rejected.value} />
          )}
        </div>
      ) : null}
    </Collapsible>
  );
}

/** The document template a step filled: its name and version, with its file ids for support. */
export function StepTemplateProvenance({ payload }: { payload: RunStep["output_payload_json"] }) {
  const t = useTranslations();
  const template = templateProvenance(payload);
  if (!template) return null;
  const ids = [
    template.assetId ? t("flow_run_template_asset_badge", { id: template.assetId }) : null,
    template.fileId ? t("flow_run_template_file_badge", { id: template.fileId }) : null,
    template.checksum
  ].filter(Boolean);
  return (
    <div className="flex flex-col gap-0.5">
      <p className="text-ax-text m-0 text-sm font-medium">
        {t("flow_run_template_provenance_label")}
      </p>
      <p className="text-ax-text m-0 text-sm break-words">
        {template.name}
        {template.version !== null ? (
          <span className="text-ax-text-secondary">
            {" "}
            · {t("flow_run_template_version_badge", { version: template.version })}
          </span>
        ) : null}
      </p>
      {ids.length > 0 ? (
        <p className="text-ax-text-secondary m-0 font-mono text-xs break-all">{ids.join(" · ")}</p>
      ) : null}
    </div>
  );
}

/** What was sent in at run time: the text read out of the files and its format. */
export function StepRuntimeInputSummary({
  result
}: {
  result: Pick<RunStep, "input_payload_json" | "runtime_input_file_ids">;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const summary = runtimeInputSummary(result);
  if (!summary) return null;
  const facts = [
    summary.extractedTextLength !== null
      ? t("flow_run_extracted_text_badge", {
          count: formatCount(summary.extractedTextLength, locale)
        })
      : null,
    summary.inputFormat
      ? t("flow_run_input_format_badge", {
          format: INPUT_FORMATS.has(summary.inputFormat)
            ? t(`flow_runtime_input_format_${summary.inputFormat}`)
            : summary.inputFormat
        })
      : null
  ].filter(Boolean);
  if (facts.length === 0) return null;
  return <p className="text-ax-text-secondary m-0 text-sm">{facts.join(" · ")}</p>;
}
