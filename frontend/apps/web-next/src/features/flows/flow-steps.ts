/**
 * What a flow's steps read and the orders the editor sends, derived from the
 * definition and, for an AI step, its assistant's prompt (pure,
 * unit-tested). The core is the authority on reads: this mirrors the
 * reference editor's reading of a step's bindings, input source and prompt
 * (`flowInputBindings.ts`, `flowStepMaterial.ts` in apps/web) for display.
 * The prompt lives on the step assistant, so the caller passes it in.
 */
import type { FlowPublic, FlowStep, FlowStepSlot } from "./flows-api";

/** One source a step reads. */
export type StepRead =
  /** What the run is given: the uploaded material, the run form, system values. */
  | { kind: "flow_input" }
  /** An earlier step by its 1-based order; `step` is null when no such step exists. */
  | { kind: "step"; order: number; step: FlowStep | null }
  /** A web address fetched when the step runs. */
  | { kind: "http" }
  /** An MCP tool called when the step runs. */
  | { kind: "tool" };

/** The flow's steps in run order. */
export function stepsInOrder(flow: Pick<FlowPublic, "steps">): FlowStep[] {
  return [...flow.steps].sort((a, b) => a.step_order - b.step_order);
}

/** A step's name: what its author called it (`user_description`), or null for none. */
export function stepName(step: Pick<FlowStep, "user_description">): string | null {
  return step.user_description?.trim() || null;
}

const TOKEN = /\{\{\s*([^{}]+?)\s*\}\}/g;
const STEP_ALIAS = /^step_(\d+)(?:$|[._])/;
/** A read of a step a change removed, as the reference editor marks it (`step_2_deleted`). */
const DELETED_STEP_ALIAS = /^step_(\d+)_deleted/;
/** The reference editor's word for "the step before this one". */
const PREVIOUS_STEP_TOKEN = "föregående_steg";

/** The references a template reads (`{{step_2.output.text}}` reads `step_2.output.text`). */
export function tokensOf(template: string): string[] {
  return [...template.matchAll(TOKEN)].map((match) => match[1]!.trim());
}

/**
 * A template as its text and the references in it, in order. A reference
 * keeps the text it was written as (`raw`, `{{ step_2.output.text }}`), so
 * the parts join back into the template.
 */
export type TemplatePart =
  { kind: "text"; text: string } | { kind: "read"; token: string; raw: string };

export function templateParts(template: string): TemplatePart[] {
  const parts: TemplatePart[] = [];
  let cursor = 0;
  for (const match of template.matchAll(TOKEN)) {
    const start = match.index ?? 0;
    if (start > cursor) parts.push({ kind: "text", text: template.slice(cursor, start) });
    parts.push({ kind: "read", token: match[1]!.trim(), raw: match[0] });
    cursor = start + match[0].length;
  }
  if (cursor < template.length) parts.push({ kind: "text", text: template.slice(cursor) });
  return parts;
}

/**
 * What one reference of a step reads: an earlier step (by its alias, by its
 * name, or as the step before), a step a change removed or one that is not
 * earlier, or else what the run is given (a run input or a system value).
 */
export type ReadTarget =
  | { kind: "step"; order: number; via: "alias" | "name" | "previous" }
  | { kind: "deleted"; order: number }
  | { kind: "not_earlier"; order: number }
  | { kind: "flow_input" };

export function readTarget(
  token: string,
  step: Pick<FlowStep, "step_order">,
  steps: readonly FlowStep[]
): ReadTarget {
  const removed = DELETED_STEP_ALIAS.exec(token);
  if (removed) return { kind: "deleted", order: Number(removed[1]) };
  const alias = STEP_ALIAS.exec(token);
  if (alias) {
    const order = Number(alias[1]);
    return order < step.step_order
      ? { kind: "step", order, via: "alias" }
      : { kind: "not_earlier", order };
  }
  const earlier = steps
    .filter((candidate) => candidate.step_order < step.step_order)
    .sort((a, b) => a.step_order - b.step_order);
  if (token === PREVIOUS_STEP_TOKEN) {
    const previous = earlier.at(-1);
    return previous
      ? { kind: "step", order: previous.step_order, via: "previous" }
      : { kind: "flow_input" };
  }
  // A step can be read by its name; any other token is a run input or a
  // system value.
  const named = earlier.find((candidate) => stepName(candidate) === token);
  return named ? { kind: "step", order: named.step_order, via: "name" } : { kind: "flow_input" };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** The bindings' question and the step aliases its source refs name. */
function bindingsOf(step: FlowStep): { question: string; refs: string[] } {
  const bindings = isRecord(step.input_bindings) ? step.input_bindings : {};
  const question = typeof bindings.question === "string" ? bindings.question : "";
  const refs = Array.isArray(bindings.source_refs)
    ? bindings.source_refs.flatMap((ref) =>
        isRecord(ref) && typeof ref.step_ref === "string" ? [ref.step_ref] : []
      )
    : [];
  return { question, refs };
}

/** The whole-reference arguments of a tool step (`{{step_2.output.text}}`). */
function toolArgumentTokens(step: FlowStep): string[] {
  const config = isRecord(step.input_config) ? step.input_config : {};
  const tool = isRecord(config.tool) ? config.tool : {};
  const args = isRecord(tool.arguments) ? tool.arguments : {};
  return Object.values(args).flatMap((value) => (typeof value === "string" ? tokensOf(value) : []));
}

type ReadFacts = {
  /** Earlier steps named in the step's bindings or tool arguments (alias or name). */
  named: Set<number>;
  /** Earlier steps read by position: the previous step, or all earlier ones. */
  implicit: Set<number>;
  /** Steps a change removed that the bindings still name (`step_2_deleted`). */
  deleted: Set<number>;
  readsFlowInput: boolean;
  extra: StepRead[];
};

/** A step's prompt by its assistant id, for the steps whose assistant has been read. */
export type StepPrompts = ReadonlyMap<string, string>;

function readFacts(step: FlowStep, steps: readonly FlowStep[], prompt = ""): ReadFacts {
  const earlier = steps
    .filter((candidate) => candidate.step_order < step.step_order)
    .sort((a, b) => a.step_order - b.step_order);
  const facts: ReadFacts = {
    named: new Set(),
    implicit: new Set(),
    deleted: new Set(),
    readsFlowInput: false,
    extra: []
  };
  const readPrevious = () => {
    const previous = earlier.at(-1);
    if (previous) facts.implicit.add(previous.step_order);
    else facts.readsFlowInput = true;
  };

  const readToken = (token: string) => {
    const target = readTarget(token, step, steps);
    switch (target.kind) {
      case "deleted":
        facts.deleted.add(target.order);
        break;
      case "not_earlier":
        break;
      case "step":
        if (target.via === "previous") facts.implicit.add(target.order);
        else facts.named.add(target.order);
        break;
      case "flow_input":
        facts.readsFlowInput = true;
        break;
    }
  };

  // The prompt is read whatever the step's material is.
  tokensOf(prompt).forEach(readToken);
  const { question, refs } = bindingsOf(step);
  if (question.trim() || refs.length > 0) {
    tokensOf(question).forEach(readToken);
    refs.forEach(readToken);
    return facts;
  }
  switch (step.input_source) {
    case "previous_step":
      readPrevious();
      break;
    case "all_previous_steps":
      if (earlier.length === 0) facts.readsFlowInput = true;
      earlier.forEach((candidate) => facts.implicit.add(candidate.step_order));
      break;
    case "flow_input":
      facts.readsFlowInput = true;
      break;
    case "http_get":
      facts.extra.push({ kind: "http" });
      break;
    case "tool":
      toolArgumentTokens(step).forEach(readToken);
      facts.extra.push({ kind: "tool" });
      break;
  }
  return facts;
}

/**
 * What a step reads, each source once: earlier steps in run order first,
 * then the run's input, the web or a tool. Bindings, when the step has
 * any, decide its material alone; otherwise its input source does. What
 * its prompt reads (`prompts`, by assistant id) comes on top.
 */
export function stepReads(
  step: FlowStep,
  steps: readonly FlowStep[],
  prompts: StepPrompts = new Map()
): StepRead[] {
  const facts = readFacts(step, steps, prompts.get(step.assistant_id));
  const orders = new Set([...facts.named, ...facts.implicit]);
  const reads: StepRead[] = [
    ...[...orders].map((order) => ({
      order,
      step: steps.find((candidate) => candidate.step_order === order) ?? null
    })),
    ...[...facts.deleted]
      .filter((order) => !orders.has(order))
      .map((order) => ({ order, step: null }))
  ]
    .sort((a, b) => a.order - b.order)
    .map((read) => ({ kind: "step" as const, ...read }));
  if (facts.readsFlowInput) reads.push({ kind: "flow_input" });
  return [...reads, ...facts.extra];
}

/**
 * The later steps that name a step in their bindings, tool arguments or
 * prompt, in run order: removing the step leaves them without it. A step that reads
 * "the previous step" reads whichever step comes before it after a change.
 */
export function stepReaders(
  step: FlowStep,
  steps: readonly FlowStep[],
  prompts: StepPrompts = new Map()
): FlowStep[] {
  return steps
    .filter((later) => later.step_order > step.step_order)
    .filter((later) =>
      readFacts(later, steps, prompts.get(later.assistant_id)).named.has(step.step_order)
    )
    .sort((a, b) => a.step_order - b.step_order);
}

const slotOf = (step: FlowStep): FlowStepSlot => ({ step_id: step.id ?? null });

/**
 * The step order with one step moved `delta` places (-1 up, +1 down), or
 * null when it cannot move that way.
 */
export function orderWithMove(
  steps: readonly FlowStep[],
  stepId: string,
  delta: -1 | 1
): FlowStepSlot[] | null {
  const ordered = [...steps].sort((a, b) => a.step_order - b.step_order);
  const from = ordered.findIndex((step) => step.id === stepId);
  const to = from + delta;
  if (from < 0 || to < 0 || to >= ordered.length) return null;
  const moved = [...ordered];
  [moved[from], moved[to]] = [moved[to]!, moved[from]!];
  return moved.map(slotOf);
}

/** The step order without one step: the core removes a saved step its order leaves out. */
export function orderWithout(steps: readonly FlowStep[], stepId: string): FlowStepSlot[] {
  return [...steps]
    .sort((a, b) => a.step_order - b.step_order)
    .filter((step) => step.id !== stepId)
    .map(slotOf);
}

/** The step order with the first new step (`new_steps[0]`) at 1-based `position`. */
export function orderWithNewStep(steps: readonly FlowStep[], position: number): FlowStepSlot[] {
  const ordered = [...steps].sort((a, b) => a.step_order - b.step_order).map(slotOf);
  const at = Math.min(Math.max(position - 1, 0), ordered.length);
  return [...ordered.slice(0, at), { new_step: 0 }, ...ordered.slice(at)];
}
