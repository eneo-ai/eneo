import { beforeEach, describe, expect, it, vi } from "vitest";
import { advancePublishedBindings, initialRollout } from "./skill-rollout";
import type { Schema } from "@/lib/api/models";

const post = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({ browserApi: { POST: post } }));

const ok = (data: unknown) =>
  Promise.resolve({ data, response: new Response("{}", { status: 200 }) });

beforeEach(() => {
  post.mockReset();
});

describe("published Skill binding rollout", () => {
  it("uses the reviewed versions and walks assistant chunks before app chunks", async () => {
    post.mockImplementation((path: string, options: { body: { cursor?: string | null } }) => {
      if (path.endsWith("personal-chat/advance/")) return ok({});
      if (path.endsWith("assistants/advance/"))
        return ok({
          counts: { advanced: 1, concurrent_change: 0, incompatible: 0 },
          next_cursor: options.body.cursor ? null : "next",
          outcomes: []
        });
      return ok({
        counts: { advanced: 2, concurrent_change: 0, incompatible: 0 },
        next_cursor: null,
        outcomes: []
      });
    });
    const updates: unknown[] = [];
    const adoption: Schema<"SkillAdoptionProjectionPagePublic"> = {
      summary: {
        assistant_count: 0,
        app_count: 0,
        distinct_space_count: 0,
        behind_published_count: 0,
        personal_chat: { revision_id: "old", revision_number: 1, drift: "behind" },
        revision_counts: []
      },
      items: [],
      limit: 1
    };
    const outcome = await advancePublishedBindings({
      skillId: "skill",
      revisionId: "published",
      adoption,
      scope: { assistants: true, apps: true },
      stopped: () => false,
      onProgress: (update) => updates.push(update)
    });
    expect(outcome).toBe("completed");
    expect(post.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/skills/organization/{skill_id}/personal-chat/advance/",
      "/api/v1/skills/organization/{skill_id}/assistants/advance/",
      "/api/v1/skills/organization/{skill_id}/assistants/advance/",
      "/api/v1/skills/organization/{skill_id}/apps/advance/"
    ]);
    expect(post.mock.calls[0]![1].body).toEqual({
      expected_pinned_revision_id: "old",
      expected_published_revision_id: "published"
    });
    expect(post.mock.calls[2]![1].body.cursor).toBe("next");
    expect(updates).toContainEqual({ status: "completed", stage: "done" });
  });

  it("stops between bounded chunks and leaves app bindings untouched", async () => {
    let stopped = false;
    post.mockImplementation(() => {
      stopped = true;
      return ok({
        counts: { advanced: 1, concurrent_change: 0, incompatible: 0 },
        next_cursor: "next",
        outcomes: []
      });
    });
    const outcome = await advancePublishedBindings({
      skillId: "skill",
      revisionId: "published",
      adoption: null,
      scope: { assistants: true, apps: true },
      stopped: () => stopped,
      onProgress: () => {}
    });
    expect(outcome).toBe("stopped");
    expect(post).toHaveBeenCalledTimes(1);
  });

  it("keeps a failed first stage visible for retry", async () => {
    post.mockRejectedValue(new Error("network"));
    const updates: unknown[] = [];
    const outcome = await advancePublishedBindings({
      skillId: "skill",
      revisionId: "published",
      adoption: null,
      scope: { assistants: true, apps: true },
      stopped: () => false,
      onProgress: (update) => updates.push(update)
    });
    expect(outcome).toBe("failed");
    expect(updates).toContainEqual({ status: "failed", stage: "done" });
    expect(initialRollout({ assistants: true, apps: true }, null, "published").personalChat).toBe(
      "failed"
    );
  });
});
