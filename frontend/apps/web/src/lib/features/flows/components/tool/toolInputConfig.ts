import type { components, FlowStep } from "@eneo/eneo-js";
import { isJsonObject, type JsonObject } from "$lib/features/flows/jsonObject";
import {
  classifyVariable,
  extractTemplateTokens,
  readsFlowInputToken,
  referencedStepOrder,
  TEMPLATE_TOKEN_PATTERN_SOURCE,
  type VariableClassificationContext
} from "$lib/features/flows/flowVariableTokens";

/** One tool a step of the flow can name, with the level that refuses it when one does. */
export type FlowToolOption = components["schemas"]["FlowToolOptionPublic"];

/**
 * The tools a step of the flow can name, as far as the editor has them. While
 * a loaded list is asked for again it stays, marked `refreshing`.
 * `classificationsEnabled` is the organization's switch, as the list gives it.
 */
export type ToolOptionsLoad =
  | { status: "loading" }
  | { status: "failed"; message: string }
  | {
      status: "loaded";
      options: FlowToolOption[];
      classificationsEnabled: boolean;
      refreshing: boolean;
    };

/** The tools of a loaded list; none while the list is loading or failed. */
export function listedToolOptions(load: ToolOptionsLoad): FlowToolOption[] {
  return load.status === "loaded" ? load.options : [];
}

const TOOL_INPUT_CONFIG_KEY = "tool";
const TOOL_CONFIG_KEYS = ["mcp_server_id", "tool_id", "arguments"];

/** What an editable step stores for its tool: which tool, and a value per argument. */
export type ToolInputConfig = {
  mcp_server_id: string;
  tool_id: string;
  arguments: JsonObject;
};

/** A stored tool choice; `hasOtherKeys` when it holds more than the keys the editor writes. */
export type StoredToolInputConfig = ToolInputConfig & { hasOtherKeys: boolean };

/** The tool a step's `input_config` names, or null while none is chosen. */
export function readToolInputConfig(inputConfig: unknown): StoredToolInputConfig | null {
  const stored = isJsonObject(inputConfig) ? inputConfig[TOOL_INPUT_CONFIG_KEY] : null;
  if (!isJsonObject(stored)) return null;
  const { mcp_server_id, tool_id } = stored;
  if (typeof mcp_server_id !== "string" || !mcp_server_id) return null;
  if (typeof tool_id !== "string" || !tool_id) return null;
  return {
    mcp_server_id,
    tool_id,
    arguments: isJsonObject(stored.arguments) ? stored.arguments : {},
    hasOtherKeys: Object.keys(stored).some((key) => !TOOL_CONFIG_KEYS.includes(key))
  };
}

/** True for a step that reads from a tool and names none yet. */
export function lacksChosenTool(step: Pick<FlowStep, "input_source" | "input_config">): boolean {
  return step.input_source === "tool" && readToolInputConfig(step.input_config) === null;
}

/** The listed tool a stored choice names, or null when the list does not have it. */
export function findToolOption(
  options: readonly FlowToolOption[],
  config: Pick<ToolInputConfig, "mcp_server_id" | "tool_id"> | null
): FlowToolOption | null {
  return (
    options.find(
      (option) =>
        option.mcp_server_id === config?.mcp_server_id && option.tool_id === config?.tool_id
    ) ?? null
  );
}

/**
 * `inputConfig` with its tool choice replaced, or removed for null. The step's
 * other input settings stay. Only the three editable keys are written: the pin
 * of a published step is the server's to set.
 */
export function withToolInputConfig(
  inputConfig: unknown,
  config: ToolInputConfig | null
): JsonObject | null {
  const next: JsonObject = isJsonObject(inputConfig) ? { ...inputConfig } : {};
  delete next[TOOL_INPUT_CONFIG_KEY];
  if (config) {
    next[TOOL_INPUT_CONFIG_KEY] = {
      mcp_server_id: config.mcp_server_id,
      tool_id: config.tool_id,
      arguments: config.arguments
    };
  }
  return Object.keys(next).length > 0 ? next : null;
}

/**
 * The stored value of one argument, undefined while it has none. A tool may
 * name an argument like a member every object inherits (`constructor`), so
 * only the object's own keys count.
 */
export function readArgument(stored: JsonObject, name: string): unknown {
  return Object.hasOwn(stored, name) ? stored[name] : undefined;
}

/**
 * `stored` with one argument set, or left out for undefined. Built from
 * entries, which makes every name (`__proto__` too) a plain key of its own.
 */
export function withArgument(stored: JsonObject, name: string, value: unknown): JsonObject {
  const entries = Object.entries(stored).filter(([key]) => key !== name);
  return Object.fromEntries(value === undefined ? entries : [...entries, [name, value]]);
}

const VARIABLE = new RegExp(TEMPLATE_TOKEN_PATTERN_SOURCE);
const WHOLE_VARIABLE = new RegExp(`^${TEMPLATE_TOKEN_PATTERN_SOURCE}$`);

/** The variable an argument reads: its value is one `{{…}}` and nothing else. */
export function boundVariableToken(value: unknown): string | null {
  if (typeof value !== "string") return null;
  return WHOLE_VARIABLE.exec(value.trim())?.[1]?.trim() ?? null;
}

/** True when a value holds a `{{…}}` anywhere, which the server reads as a reference. */
export function holdsVariable(value: unknown): boolean {
  if (typeof value === "string") return VARIABLE.test(value);
  if (Array.isArray(value)) return value.some(holdsVariable);
  return isJsonObject(value) && Object.values(value).some(holdsVariable);
}

/**
 * What an argument's value reads, wherever in the value a reference sits: the
 * earlier steps, through the editor's one resolver for a step named by
 * number, by name or as the previous step, and whether it reads the run's
 * own input (a form field or what is sent in), as a step's source line says.
 */
export function argumentReads(
  value: unknown,
  context: VariableClassificationContext
): { stepOrders: number[]; readsFlowInput: boolean } {
  const orders = new Set<number>();
  let readsFlowInput = false;
  const visit = (item: unknown): void => {
    if (typeof item === "string") {
      for (const token of extractTemplateTokens(item)) {
        const order = referencedStepOrder(token, context);
        if (order !== null) orders.add(order);
        else if (
          classifyVariable(token, context) === "field" ||
          readsFlowInputToken(token, context)
        ) {
          readsFlowInput = true;
        }
      }
    } else if (Array.isArray(item)) {
      item.forEach(visit);
    } else if (isJsonObject(item)) {
      Object.values(item).forEach(visit);
    }
  };
  visit(value);
  return { stepOrders: [...orders].sort((a, b) => a - b), readsFlowInput };
}

/**
 * `step` with `rewrite` applied to each argument of its tool that is one whole
 * variable, and the same step when none changes. This is the one rule for
 * which argument is a reference: a fixed value is the author's own text, also
 * when it holds a name in braces.
 */
export function rewriteBoundToolArguments(
  step: FlowStep,
  rewrite: (reference: string) => string
): FlowStep {
  const inputConfig = step.input_config;
  if (step.input_source !== "tool" || !isJsonObject(inputConfig)) return step;
  const tool = inputConfig[TOOL_INPUT_CONFIG_KEY];
  if (!isJsonObject(tool) || !isJsonObject(tool.arguments)) return step;
  let changed = false;
  const entries = Object.entries(tool.arguments).map(([name, value]): [string, unknown] => {
    if (typeof value !== "string" || boundVariableToken(value) === null) return [name, value];
    const next = rewrite(value);
    changed ||= next !== value;
    return [name, next];
  });
  if (!changed) return step;
  return {
    ...step,
    input_config: {
      ...inputConfig,
      [TOOL_INPUT_CONFIG_KEY]: { ...tool, arguments: Object.fromEntries(entries) }
    }
  };
}

/** The arguments of a tool step that are one whole variable, as stored. */
export function boundToolArguments(step: FlowStep): string[] {
  const found: string[] = [];
  rewriteBoundToolArguments(step, (reference) => {
    found.push(reference);
    return reference;
  });
  return found;
}

type JsonRead = { ok: true; value: unknown } | { ok: false };

export function readJson(text: string): JsonRead {
  try {
    return { ok: true, value: JSON.parse(text) };
  } catch {
    return { ok: false };
  }
}

/** JSON text with each object's keys in one order: the server's jsonb keeps no key order. */
function orderedJson(value: unknown): string {
  return JSON.stringify(value, (_key, inner: unknown) =>
    isJsonObject(inner)
      ? Object.fromEntries(
          Object.entries(inner).sort(([left], [right]) =>
            left < right ? -1 : left > right ? 1 : 0
          )
        )
      : inner
  );
}

/** True when two values are stored as the same JSON, whatever order an object's keys come in. */
export function sameJson(left: unknown, right: unknown): boolean {
  return orderedJson(left) === orderedJson(right);
}

/**
 * The stored arguments a field of the step editor writes: one argument's row
 * (`only`), or the JSON field that takes every argument without a row of its
 * own (`except` the arguments that have one).
 */
export type ArgumentsScope = { only: string } | { except: readonly string[] };

/** The part of `stored` a field with `scope` writes. */
function scopedArguments(stored: JsonObject, scope: ArgumentsScope): JsonObject {
  return Object.fromEntries(
    Object.entries(stored).filter(([name]) =>
      "only" in scope ? name === scope.only : !scope.except.includes(name)
    )
  );
}

/**
 * Text typed in a field for a step's tool arguments that the step cannot
 * hold, with the tool and the field's stored arguments when it was typed. The
 * step keeps those arguments, so the text stays unsaved until it is fixed.
 */
export type ToolArgumentsDraft = {
  text: string;
  scope: ArgumentsScope;
  typedAgainst: ToolInputConfig;
};

/** The key a step's drafts are kept under: one per row, one for the JSON field. */
export function draftPlace(scope: ArgumentsScope): string {
  return "only" in scope ? `argument:${scope.only}` : "arguments";
}

/** The draft of a text typed in the field with `scope` while the step holds `config`. */
export function typedDraft(
  text: string,
  scope: ArgumentsScope,
  config: ToolInputConfig
): ToolArgumentsDraft {
  return {
    text,
    scope,
    typedAgainst: {
      mcp_server_id: config.mcp_server_id,
      tool_id: config.tool_id,
      arguments: scopedArguments(config.arguments, scope)
    }
  };
}

/**
 * The draft's text while the step still holds the tool and the field's
 * arguments it was typed against; null once another tool or other values for
 * those arguments are stored, which replace the text.
 */
export function keptDraftText(
  draft: ToolArgumentsDraft | null | undefined,
  config: ToolInputConfig | null
): string | null {
  if (!draft || !config) return null;
  const { typedAgainst, scope } = draft;
  return typedAgainst.mcp_server_id === config.mcp_server_id &&
    typedAgainst.tool_id === config.tool_id &&
    sameJson(typedAgainst.arguments, scopedArguments(config.arguments, scope))
    ? draft.text
    : null;
}

/**
 * True when a value read from a number field or from JSON holds a number
 * JavaScript did not keep as written: one beyond the finite range (`1e999`),
 * or a whole number beyond the safe integer range, which reading rounds
 * (9007199254740993 to …992). Such a literal always reads as a value outside
 * that range, so the read value tells.
 */
export function holdsInexactNumber(value: unknown): boolean {
  if (typeof value === "number") {
    return !Number.isFinite(value) || (Number.isInteger(value) && !Number.isSafeInteger(value));
  }
  if (Array.isArray(value)) return value.some(holdsInexactNumber);
  return isJsonObject(value) && Object.values(value).some(holdsInexactNumber);
}
