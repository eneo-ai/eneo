import { m } from "$lib/paraglide/messages";
import type { AnalysisStep } from "./analysisStep";
export function analysisStepLabels(step: AnalysisStep | null) {
  if (!step) return null;
  const groups = step.groups.join(", ");
  switch (step.kind) {
    case "inspect":
      return { running: m.tool_inspect_structure(), done: m.tool_inspect_structure_done() };
    case "check":
      return { running: m.tool_check_data(), done: m.tool_check_data_done() };
    case "sum":
      return groups
        ? {
            running: m.tool_aggregate_groups({ groups }),
            done: m.tool_aggregate_groups_done({ groups })
          }
        : { running: m.tool_aggregate_values(), done: m.tool_aggregate_values_done() };
    case "count":
      return groups
        ? { running: m.tool_count_groups({ groups }), done: m.tool_count_groups_done({ groups }) }
        : { running: m.tool_count_rows(), done: m.tool_count_rows_done() };
    case "query":
      return { running: m.tool_query_rows(), done: m.tool_query_rows_done() };
  }
}
