import { isJsonObject, type SecurityClassification } from "./step-types";

/**
 * The names of the organisation's security classes, by level. The list
 * endpoint names them all; when it answers nothing (a member it refuses, or
 * an error), the classes the space payload already carries name the levels
 * they use: the space's own and those of its models and MCP servers. A
 * level nobody names stays a number. Pure and unit-tested.
 */

type Named = { name: string; security_level: number };

function namedOf(value: unknown): Named | null {
  if (!isJsonObject(value)) return null;
  const { name, security_level: level } = value;
  return typeof name === "string" && name.trim() && typeof level === "number"
    ? { name: name.trim(), security_level: level }
    : null;
}

/** What the space payload carries that names a class. */
export type ClassifiedSpace = {
  security_classification?: unknown;
  completion_models?: readonly { security_classification?: unknown }[];
  embedding_models?: readonly { security_classification?: unknown }[];
  transcription_models?: readonly { security_classification?: unknown }[];
  mcp_servers?: readonly { security_classification?: unknown }[];
};

/** The classes known by name, lowest level first; the list's names win over the space's. */
export function knownClassifications(
  listing: readonly SecurityClassification[] | undefined,
  space: ClassifiedSpace
): Named[] {
  const byLevel = new Map<number, string>();
  const add = (value: unknown) => {
    const named = namedOf(value);
    if (named && !byLevel.has(named.security_level)) {
      byLevel.set(named.security_level, named.name);
    }
  };
  for (const item of listing ?? []) add(item);
  add(space.security_classification);
  for (const list of [
    space.completion_models,
    space.embedding_models,
    space.transcription_models,
    space.mcp_servers
  ]) {
    for (const item of list ?? []) add(item.security_classification);
  }
  return [...byLevel]
    .map(([security_level, name]) => ({ security_level, name }))
    .sort((left, right) => left.security_level - right.security_level);
}

type Translate = (key: string, values?: Record<string, string | number>) => string;

/** A level's name, "Nivå N" when no known class has it, or "none" for no level. */
export function levelName(level: number | null, known: readonly Named[], t: Translate): string {
  if (level === null) return t("flow_step_editor_classification_none");
  return (
    known.find((item) => item.security_level === level)?.name ??
    t("flow_step_editor_classification_level", { level })
  );
}
