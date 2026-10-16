import {
  boundVariableToken,
  holdsVariable,
  readToolInputConfig
} from "$lib/features/flows/components/tool/toolInputConfig";
import { getFlowFormFieldVariableExpression } from "$lib/features/flows/flowFormSchema";
import type { AIBuilderSessionTool, FormFieldSpec, StepSpec } from "./protocol";

/** Where one argument of a proposed tool step gets its value. */
export type BuilderToolArgument =
  | { name: string; kind: "fixed"; text: string }
  /** A field of the run form, by the label the form shows. */
  | { name: string; kind: "run_input"; label: string }
  /** An earlier step's result: the step's number and, when it names one, its field. */
  | { name: string; kind: "earlier_step"; stepNumber: number; field: string | null }
  /** Any other value that reads something, shown as written. */
  | { name: string; kind: "reference"; text: string };

export interface BuilderToolStep {
  /** Null when the space's tool list does not name the tool (any more). */
  tool: { serverName: string; toolName: string } | null;
  arguments: BuilderToolArgument[];
}

/**
 * What a proposed tool step calls and where each argument comes from, in the
 * words the editor and the flow graph use. Null for a step that reads no tool.
 * The plan names tools by id, so their names come from the session's list.
 */
export function describeBuilderToolStep(
  step: Pick<StepSpec, "input_source" | "input_config">,
  context: {
    tools: readonly AIBuilderSessionTool[];
    formFields: readonly FormFieldSpec[];
    /** The 1-based position of a planned step, by the ref a reference names it with. */
    stepNumberOf: (planStepRef: string) => number | null;
  }
): BuilderToolStep | null {
  if (step.input_source !== "tool") return null;
  const config = readToolInputConfig(step.input_config);
  if (config === null) return null;
  const listed = context.tools.find(
    (tool) => tool.mcp_server_id === config.mcp_server_id && tool.tool_id === config.tool_id
  );
  return {
    tool: listed ? { serverName: listed.mcp_server_name, toolName: listed.tool_name } : null,
    arguments: Object.entries(config.arguments).map(([name, value]) =>
      describeArgument(name, value, context)
    )
  };
}

function describeArgument(
  name: string,
  value: unknown,
  context: Parameters<typeof describeBuilderToolStep>[1]
): BuilderToolArgument {
  const text = typeof value === "string" ? value : JSON.stringify(value);
  if (!holdsVariable(value)) return { name, kind: "fixed", text };
  const token = boundVariableToken(value);
  if (token === null) return { name, kind: "reference", text };
  const field = context.formFields.find(
    (candidate) => getFlowFormFieldVariableExpression(candidate.name) === token
  );
  if (field) return { name, kind: "run_input", label: field.label || field.name };
  // `<step>.output.structured.<field>`, as the compiler writes an earlier step's field.
  const [head, ...path] = token.split(".").map((segment) => segment.trim());
  const stepNumber = context.stepNumberOf(head);
  if (stepNumber === null) return { name, kind: "reference", text };
  const structured = path[0] === "output" && path[1] === "structured";
  const fieldPath = structured ? path.slice(2).join(".") : "";
  return { name, kind: "earlier_step", stepNumber, field: fieldPath === "" ? null : fieldPath };
}
