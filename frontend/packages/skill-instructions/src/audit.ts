import type { components } from "@eneo/eneo-js";
import { referenceUri, type InstructionTarget } from "./references";

type Schema = components["schemas"];
type Evidence = Schema["SkillActivationEvidenceV3"];
export type ReferenceAuditRow = {
  id: string;
  source: string;
  sourceRevision: number | null;
  label: string;
  target: InstructionTarget;
  state: "loaded" | "called" | "available" | "unavailable" | "not_checked";
  callOrders: number[];
};

/** Joins persisted identities with observed calls; it does not infer model intent. */
export function referenceAuditRows(
  evidence: Evidence,
  calls: Schema["ToolCallInfo"][],
): ReferenceAuditRow[] {
  const sources = new Map(
    [...evidence.available, ...(evidence.helpers ?? [])].map((item) => [
      item.skill_revision_id,
      item,
    ]),
  );
  const seen = new Set<string>();
  return (evidence.instruction_references ?? []).flatMap((reference) => {
    const target = reference.target;
    const id = `${reference.source_revision_id}:${referenceUri(target)}`;
    if (seen.has(id)) return [];
    seen.add(id);
    const tools = (evidence.reference_tools ?? []).filter((tool) => {
      if (target.kind === "function") return tool.purpose === target.purpose;
      if (target.kind === "skill") return false;
      return (
        tool.purpose === "general" &&
        tool.server_id === target.server_id &&
        (target.kind === "mcp_server" || tool.tool_name === target.tool_name)
      );
    });
    const callOrders = calls.flatMap((call, index) =>
      tools.some(
        (tool) =>
          call.mcp_tool_name === tool.model_name &&
          call.tool_name === tool.tool_name,
      )
        ? [index + 1]
        : [],
    );
    const source = sources.get(reference.source_revision_id);
    const state =
      target.kind === "skill"
        ? "loaded"
        : callOrders.length
          ? "called"
          : !evidence.references_prepared
            ? "not_checked"
            : tools.length
              ? "available"
              : "unavailable";
    return [
      {
        id,
        source:
          source?.display_name ?? source?.slug ?? reference.source_revision_id,
        sourceRevision: source?.revision_number ?? null,
        label: reference.label,
        target,
        state,
        callOrders,
      },
    ];
  });
}
