import { queryOptions } from "@tanstack/react-query";
import { unwrap } from "@/lib/api/errors";
import { flowsApi } from "./flows-api";
import type { FlowFunctionPublic, FlowFunctionToolPublic, FunctionStep } from "./types";

/**
 * The functions a function step can call in a space: each purpose, whether
 * the space enables it, and the tools of the provider a run reaches. The
 * same list the chat's list_functions tool reads.
 */
export function flowFunctionsQueryOptions(spaceId: string) {
  return queryOptions({
    queryKey: ["flows", "functions", spaceId] as const,
    queryFn: ({ signal }) =>
      unwrap(
        flowsApi.GET("/api/v1/flows/functions/", {
          params: { query: { space_id: spaceId } },
          signal
        })
      ),
    staleTime: 60_000
  });
}

/**
 * Whether a function step can run as it is: "ok", or why not. "unknown"
 * while the list has not arrived.
 */
export type FunctionAvailability = "ok" | "disabled" | "unavailable" | "unknown_tool" | "unknown";

export function functionOf(
  functions: readonly FlowFunctionPublic[] | undefined,
  purpose: string
): FlowFunctionPublic | null {
  return functions?.find((candidate) => candidate.purpose === purpose) ?? null;
}

export function functionAvailability(
  functions: readonly FlowFunctionPublic[] | undefined,
  step: Pick<FunctionStep, "purpose" | "tool">
): FunctionAvailability {
  const entry = functionOf(functions, step.purpose);
  if (!functions || !entry) return "unknown";
  if (!entry.enabled_in_space) return "disabled";
  if (!entry.available) return "unavailable";
  return (entry.tools ?? []).some((tool) => tool.name === step.tool) ? "ok" : "unknown_tool";
}

/** The argument names a tool takes, required ones first and starred. */
export function toolArgumentNames(tool: FlowFunctionToolPublic | null): string[] {
  const schema = tool?.input_schema as { properties?: unknown; required?: unknown } | undefined;
  const properties = schema?.properties;
  if (!properties || typeof properties !== "object") return [];
  const required = new Set(Array.isArray(schema?.required) ? (schema!.required as string[]) : []);
  const names = Object.keys(properties as Record<string, unknown>);
  return [
    ...names.filter((name) => required.has(name)).map((name) => `${name}*`),
    ...names.filter((name) => !required.has(name))
  ];
}

/** `{"prompt": ""}`: the required arguments of a tool as a start for the JSON field. */
export function toolArgumentSkeleton(tool: FlowFunctionToolPublic | null): Record<string, string> {
  const schema = tool?.input_schema as { required?: unknown } | undefined;
  const required = Array.isArray(schema?.required) ? (schema!.required as string[]) : [];
  return Object.fromEntries(required.map((name) => [name, ""]));
}
