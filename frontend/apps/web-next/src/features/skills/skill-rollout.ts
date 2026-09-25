import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

type Adoption = Schema<"SkillAdoptionProjectionPagePublic">;
export type RolloutScope = { assistants: boolean; apps: boolean };
export type RolloutProgress = {
  status: "running" | "completed" | "stopped" | "failed";
  stage: "assistants" | "apps" | "done";
  assistants: number;
  apps: number;
  incompatible: number;
  concurrent: number;
  personalChat: "pending" | "advanced" | "failed" | "not_applicable";
};

export function initialRollout(
  scope: RolloutScope,
  adoption: Adoption | null,
  revisionId: string
): RolloutProgress {
  const pinned = adoption?.summary?.personal_chat?.revision_id;
  return {
    status: "running",
    stage: scope.assistants ? "assistants" : scope.apps ? "apps" : "done",
    assistants: 0,
    apps: 0,
    incompatible: 0,
    concurrent: 0,
    personalChat:
      !scope.assistants || pinned === revisionId
        ? "not_applicable"
        : pinned
          ? "pending"
          : adoption
            ? "not_applicable"
            : "failed"
  };
}

/** The server processes one bounded page at a time and skips bindings already at the target version. */
export async function advancePublishedBindings({
  skillId,
  revisionId,
  adoption,
  scope,
  stopped,
  onProgress
}: {
  skillId: string;
  revisionId: string;
  adoption: Adoption | null;
  scope: RolloutScope;
  stopped: () => boolean;
  onProgress: (update: Partial<RolloutProgress>) => void;
}): Promise<"completed" | "stopped" | "failed"> {
  const path = { skill_id: skillId };
  const pinned = adoption?.summary?.personal_chat?.revision_id;
  const personalChat =
    scope.assistants && pinned && pinned !== revisionId
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
  try {
    if (scope.assistants) {
      let cursor: string | null = null;
      do {
        if (stopped()) {
          outcome = "stopped";
          break;
        }
        const chunk: Schema<"AssistantFleetAdvancePublic"> = await unwrap(
          browserApi.POST("/api/v1/skills/organization/{skill_id}/assistants/advance/", {
            params: { path },
            body: { expected_published_revision_id: revisionId, cursor }
          })
        );
        onProgress({
          assistants: chunk.counts.advanced,
          concurrent: chunk.counts.concurrent_change,
          incompatible: chunk.counts.incompatible
        });
        cursor = chunk.next_cursor ?? null;
      } while (cursor);
    }
    if (outcome === "completed" && scope.apps) {
      onProgress({ stage: "apps" });
      let cursor: string | null = null;
      do {
        if (stopped()) {
          outcome = "stopped";
          break;
        }
        const chunk: Schema<"AppFleetAdvancePublic"> = await unwrap(
          browserApi.POST("/api/v1/skills/organization/{skill_id}/apps/advance/", {
            params: { path },
            body: { expected_published_revision_id: revisionId, cursor }
          })
        );
        onProgress({
          apps: chunk.counts.advanced,
          concurrent: chunk.counts.concurrent_change,
          incompatible: chunk.counts.incompatible
        });
        cursor = chunk.next_cursor ?? null;
      } while (cursor);
    }
  } catch {
    outcome = "failed";
  }
  await personalChat;
  onProgress({ status: outcome, stage: "done" });
  return outcome;
}
