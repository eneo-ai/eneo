import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

type Adoption = Schema<"SkillAdoptionProjectionPagePublic">;
export type RolloutScope = { assistants: boolean; apps: boolean };
export type RolloutReason =
  Schema<"AssistantPinAdvanceIncompatibleReason"> | Schema<"AppPinAdvanceIncompatibleReason">;
type PhaseStatus = "pending" | "running" | "completed" | "stopped" | "failed";
export type RolloutPhase = {
  status: PhaseStatus;
  cursor: string | null;
  updated: number;
  total: number;
  concurrent: number;
  incompatible: number;
  reasons: Partial<Record<RolloutReason, number>>;
  error: unknown;
};
export type RolloutProgress = {
  revisionId: string;
  status: "running" | "completed" | "stopped" | "failed";
  stage: "assistants" | "apps" | "done";
  assistants: RolloutPhase | null;
  apps: RolloutPhase | null;
  personalChat: "pending" | "advanced" | "failed" | "not_applicable";
  stopRequested: boolean;
};

export function initialRollout(
  scope: RolloutScope,
  adoption: Adoption | null,
  revisionId: string,
  previous?: RolloutProgress | null
): RolloutProgress {
  const pinned = adoption?.summary?.personal_chat?.revision_id;
  const personalChat =
    !scope.assistants || pinned === revisionId
      ? "not_applicable"
      : pinned
        ? "pending"
        : adoption
          ? "not_applicable"
          : "failed";
  if (previous?.revisionId === revisionId) {
    return {
      ...previous,
      status: "running",
      stopRequested: false,
      personalChat: previous.personalChat === "advanced" ? "advanced" : personalChat
    };
  }
  const phase = (kind: "assistant_count" | "app_count"): RolloutPhase => ({
    status: "pending",
    cursor: null,
    updated: 0,
    concurrent: 0,
    incompatible: 0,
    reasons: {},
    error: null,
    total:
      adoption?.summary?.revision_counts.reduce(
        (sum, revision) => sum + (revision.revision_id === revisionId ? 0 : revision[kind]),
        0
      ) ?? 0
  });
  return {
    revisionId,
    status: "running",
    stage: scope.assistants ? "assistants" : scope.apps ? "apps" : "done",
    assistants: scope.assistants ? phase("assistant_count") : null,
    apps: scope.apps ? phase("app_count") : null,
    stopRequested: false,
    personalChat
  };
}

/** Counts describe one committed page. Keep its next cursor and completed phases for explicit resume. */
export async function advancePublishedBindings({
  skillId,
  revisionId,
  adoption,
  scope,
  stopped,
  onProgress,
  resume
}: {
  skillId: string;
  revisionId: string;
  adoption: Adoption | null;
  scope: RolloutScope;
  stopped: () => boolean;
  onProgress: (update: Partial<RolloutProgress>) => void;
  resume?: RolloutProgress | null;
}): Promise<"completed" | "stopped" | "failed"> {
  const state = initialRollout(scope, adoption, revisionId, resume);
  const path = { skill_id: skillId };
  const pinned = adoption?.summary?.personal_chat?.revision_id;
  const personalChat =
    scope.assistants && pinned && pinned !== revisionId && state.personalChat !== "advanced"
      ? unwrap(
          browserApi.POST("/api/v1/skills/organization/{skill_id}/personal-chat/advance/", {
            params: { path },
            body: {
              expected_pinned_revision_id: pinned,
              expected_published_revision_id: revisionId
            }
          })
        ).then(
          () => onProgress({ personalChat: "advanced" }),
          () => onProgress({ personalChat: "failed" })
        )
      : Promise.resolve();
  let outcome: "completed" | "stopped" | "failed" = "completed";
  for (const kind of ["assistants", "apps"] as const) {
    let phase = state[kind];
    if (!phase || phase.status === "completed") continue;
    const report = (next: RolloutPhase) => {
      phase = next;
      state[kind] = next;
      onProgress(
        kind === "assistants" ? { stage: kind, assistants: next } : { stage: kind, apps: next }
      );
    };
    try {
      do {
        if (stopped()) {
          report({ ...phase, status: "stopped" });
          outcome = "stopped";
          break;
        }
        report({ ...phase, status: "running", error: null });
        const body = { expected_published_revision_id: revisionId, cursor: phase.cursor };
        const chunk =
          kind === "assistants"
            ? await unwrap(
                browserApi.POST("/api/v1/skills/organization/{skill_id}/assistants/advance/", {
                  params: { path },
                  body
                })
              )
            : await unwrap(
                browserApi.POST("/api/v1/skills/organization/{skill_id}/apps/advance/", {
                  params: { path },
                  body
                })
              );
        const reasons = { ...phase.reasons };
        for (const item of chunk.outcomes) {
          if (item.outcome === "incompatible" && item.reason)
            reasons[item.reason] = (reasons[item.reason] ?? 0) + 1;
        }
        const updated = phase.updated + chunk.counts.advanced;
        const concurrent = phase.concurrent + chunk.counts.concurrent_change;
        const incompatible = phase.incompatible + chunk.counts.incompatible;
        report({
          ...phase,
          reasons,
          updated,
          concurrent,
          incompatible,
          total: Math.max(phase.total, updated + concurrent + incompatible),
          cursor: chunk.next_cursor ?? null,
          status: chunk.next_cursor ? "running" : "completed"
        });
      } while (phase.cursor);
    } catch (error) {
      report({ ...phase, status: "failed", error });
      outcome = "failed";
    }
    if (outcome !== "completed") break;
  }
  await personalChat;
  onProgress({ status: outcome, stage: "done" });
  return outcome;
}
