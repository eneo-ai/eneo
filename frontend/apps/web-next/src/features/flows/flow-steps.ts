/**
 * What a flow's steps read and the orders the editor sends, derived from the
 * definition alone (pure, unit-tested). The core is the authority on reads:
 * this mirrors the reference editor's reading of a step's bindings and input
 * source (`flowInputBindings.ts`, `flowStepMaterial.ts` in apps/web) for
 * display. Reads written in a step's prompt live on its assistant and are
 * not shown here; the core still guards them when steps move.
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

function tokensOf(template: string): string[] {
  return [...template.matchAll(TOKEN)].map((match) => match[1]!.trim());
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

function readFacts(step: FlowStep, steps: readonly FlowStep[]): ReadFacts {
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
    const removed = DELETED_STEP_ALIAS.exec(token);
    if (removed) {
      facts.deleted.add(Number(removed[1]));
      return;
    }
    const alias = STEP_ALIAS.exec(token);
    if (alias) {
      const order = Number(alias[1]);
      if (order < step.step_order) facts.named.add(order);
      return;
    }
    if (token === PREVIOUS_STEP_TOKEN) {
      readPrevious();
      return;
    }
    // A step can be read by its name; any other token is a run input or a
    // system value.
    const named = earlier.find((candidate) => stepName(candidate) === token);
    if (named) facts.named.add(named.step_order);
    else facts.readsFlowInput = true;
  };

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
 * any, decide alone; otherwise its input source does.
 */
export function stepReads(step: FlowStep, steps: readonly FlowStep[]): StepRead[] {
  const facts = readFacts(step, steps);
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
 * The later steps that name a step in their bindings or tool arguments, in
 * run order: removing the step leaves them without it. A step that reads
 * "the previous step" reads whichever step comes before it after a change.
 */
export function stepReaders(step: FlowStep, steps: readonly FlowStep[]): FlowStep[] {
  return steps
    .filter((later) => later.step_order > step.step_order)
    .filter((later) => readFacts(later, steps).named.has(step.step_order))
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
