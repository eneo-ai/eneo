import type { components } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";

/** The level that refuses a tool for a flow, as the server names it. */
export type UnattendedToolRefusal = components["schemas"]["UnattendedToolRefusal"];

// One sentence per level: what is wrong and who can change it. Named literally
// so a level the server adds is a type error here until it has its sentence.
const TOOL_REFUSAL_SENTENCES = {
  server_not_found: m.flow_tool_refusal_server_not_found,
  server_disabled: m.flow_tool_refusal_server_disabled,
  server_not_general: m.flow_tool_refusal_server_not_general,
  server_forwards_identity: m.flow_tool_refusal_server_forwards_identity,
  tool_not_found: m.flow_tool_refusal_tool_not_found,
  tool_removed_at_server: m.flow_tool_refusal_tool_removed_at_server,
  tool_waiting_for_review: m.flow_tool_refusal_tool_waiting_for_review,
  tool_switched_off: m.flow_tool_refusal_tool_switched_off,
  space_is_personal: m.flow_tool_refusal_space_is_personal,
  server_not_in_space: m.flow_tool_refusal_server_not_in_space,
  tool_switched_off_in_space: m.flow_tool_refusal_tool_switched_off_in_space,
  server_below_space_classification: m.flow_tool_refusal_server_below_space_classification
} satisfies Record<UnattendedToolRefusal, () => string>;

export function isUnattendedToolRefusal(value: unknown): value is UnattendedToolRefusal {
  return typeof value === "string" && Object.hasOwn(TOOL_REFUSAL_SENTENCES, value);
}

export function toolRefusalSentence(refusal: UnattendedToolRefusal): string {
  return TOOL_REFUSAL_SENTENCES[refusal]();
}

/** A tool a flow needs and cannot use, as the AI Builder names it in its answer. */
export type UnusableTool = components["schemas"]["AIBuilderToolRefusal"];

/** Why `tool` cannot be used: the refusing level's sentence, or why no flow
 *  can read the arguments its schema describes. Null for a refusal that does
 *  not say which level refuses it. */
export function unusableToolSentence(tool: UnusableTool): string | null {
  switch (tool.kind) {
    case "refused":
      return tool.refusal ? toolRefusalSentence(tool.refusal) : null;
    case "input_schema_invalid":
      return m.flow_tool_unusable_input_schema_invalid();
    case "input_schema_too_large":
      return m.flow_tool_unusable_input_schema_too_large();
  }
}
