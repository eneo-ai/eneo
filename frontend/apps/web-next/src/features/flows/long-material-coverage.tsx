"use client";

import { MetadataList, MetadataListItem } from "@astryxdesign/core/MetadataList";
import { Token } from "@astryxdesign/core/Token";
import { useTranslations } from "use-intl";
import {
  leftOutSources,
  reasonSlug,
  segmentCounts,
  type LongMaterialCoverage as Coverage
} from "./long-material";

/**
 * What a step that read long material in parts covered: complete, partial or
 * cancelled, how many segments it read with how many model calls, what the
 * result is (the record's mode: `digest` writes one answer from the notes on
 * every segment), why anything was left out, and which sources.
 */
export function LongMaterialCoverage({ coverage }: { coverage: Coverage }) {
  const t = useTranslations();
  const { read, planned } = segmentCounts(coverage);
  const leftOut = leftOutSources(coverage);
  const reasons = (coverage.reasons ?? []).map((reason) => {
    const key = `flow_editor_tools_long_material_reason_${reasonSlug(reason)}`;
    return t.has(key) ? t(key) : reason;
  });
  return (
    <MetadataList
      title={t("flow_editor_tools_long_material_coverage")}
      label={{ position: "start", width: "9rem" }}
    >
      <MetadataListItem label={t("flow_editor_tools_long_material_coverage_state")}>
        <Token
          size="sm"
          color={coverage.coverage === "complete" ? "green" : "orange"}
          label={t(`flow_editor_tools_long_material_coverage_${coverage.coverage}`)}
        />
      </MetadataListItem>
      <MetadataListItem label={t("flow_editor_tools_long_material_segments")}>
        {t("flow_editor_tools_long_material_segments_value", {
          read,
          planned,
          sources: coverage.sources.length
        })}
      </MetadataListItem>
      {(coverage.mode ?? "digest") === "digest" && coverage.coverage !== "cancelled" ? (
        <MetadataListItem label={t("flow_editor_tools_long_material_result")}>
          {t("flow_editor_tools_long_material_result_digest")}
        </MetadataListItem>
      ) : null}
      <MetadataListItem label={t("flow_editor_tools_long_material_calls")}>
        {t("flow_editor_tools_long_material_calls_value", {
          calls: coverage.map_calls + coverage.reduce_calls,
          failed: coverage.failed_calls
        })}
      </MetadataListItem>
      {reasons.length > 0 ? (
        <MetadataListItem label={t("flow_editor_tools_long_material_reasons")}>
          {reasons.join(", ")}
        </MetadataListItem>
      ) : null}
      {leftOut.length > 0 ? (
        <MetadataListItem label={t("flow_editor_tools_long_material_left_out")}>
          <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
            {leftOut.map((source) => (
              <li key={source.key}>
                {source.segments
                  ? t("flow_editor_tools_long_material_left_out_segments", {
                      title: source.title,
                      segments: source.segments,
                      planned: source.planned
                    })
                  : t("flow_editor_tools_long_material_left_out_notes", { title: source.title })}
              </li>
            ))}
          </ul>
        </MetadataListItem>
      ) : null}
    </MetadataList>
  );
}
