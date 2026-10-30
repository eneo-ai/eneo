import type { RunSummary } from "./runs-api";

type Translate = (key: string, values?: Record<string, string | number>) => string;

type StartedRun = Pick<RunSummary, "principal_type" | "started_by">;

/**
 * Who started a run, as a reader sees it: the person's or service key's name,
 * else what kind of principal it was (a backend that names no one, or an
 * account that can no longer be read).
 */
export function starterName(run: StartedRun, t: Translate): string {
  const name = run.started_by?.display_name?.trim();
  if (name) return name;
  const kind = run.started_by?.principal_type ?? run.principal_type;
  return kind === "service_key"
    ? t("flow_runs_started_by_service_key")
    : t("flow_runs_started_by_person");
}

/**
 * Whether the signed-in person started the run. Null when the run does not
 * say who started it, so a caller does not guess either way.
 */
export function startedByUser(run: Pick<RunSummary, "started_by">, userId: string): boolean | null {
  const starter = run.started_by;
  if (!starter) return null;
  return starter.principal_type === "user" && starter.id === userId;
}
