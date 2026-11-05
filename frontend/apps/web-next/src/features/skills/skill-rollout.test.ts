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
  it("uses a fresh personal-chat pin when resuming after an uncertain request", () => {
    const scope = { assistants: true, apps: true };
    const previous = {
      ...initialRollout(scope, null, "published"),
      personalChat: "failed" as const
    };
    const adoption: Schema<"SkillAdoptionProjectionPagePublic"> = {
      summary: {
        assistant_count: 0,
        app_count: 0,
        distinct_space_count: 0,
        behind_published_count: 0,
        personal_chat: { revision_id: "published", revision_number: 2, drift: "current" },
        revision_counts: []
      },
      items: [],
      limit: 1
    };
    expect(initialRollout(scope, adoption, "published", previous).personalChat).toBe(
      "not_applicable"
    );
  });

  it("resumes a failed app phase without walking completed assistants again", async () => {
    let failApps = true;
    post.mockImplementation((path: string) => {
      if (path.endsWith("apps/advance/") && failApps)
        return Promise.reject(new Error("Apps unavailable"));
      return ok({
        counts: { advanced: 1, concurrent_change: 0, incompatible: 0 },
        next_cursor: null,
        outcomes: []
      });
    });
    const scope = { assistants: true, apps: true };
    let receipt = initialRollout(scope, null, "published");
    const options = {
      skillId: "skill",
      revisionId: "published",
      adoption: null,
      scope,
      stopped: () => false,
      onProgress: (update: Partial<typeof receipt>) => {
        receipt = { ...receipt, ...update };
      }
    };
    expect(await advancePublishedBindings(options)).toBe("failed");
    failApps = false;
    expect(await advancePublishedBindings({ ...options, resume: receipt })).toBe("completed");
    expect(post.mock.calls.filter(([path]) => path.endsWith("assistants/advance/"))).toHaveLength(
      1
    );
    expect(receipt).toMatchObject({
      assistants: { status: "completed", updated: 1 },
      apps: { status: "completed", updated: 1 }
    });
  });

  it("accumulates page-local counts and preserves distinct incompatibility reasons", async () => {
    post.mockImplementation((_path: string, options: { body: { cursor: string | null } }) =>
      ok({
        counts: { advanced: 1, concurrent_change: 0, incompatible: 1 },
        outcomes: [
          { assistant_id: options.body.cursor ? "ok2" : "ok1", outcome: "advanced", reason: null },
          {
            assistant_id: options.body.cursor ? "a2" : "a1",
            outcome: "incompatible",
            reason: options.body.cursor ? "context_window" : "activation_unavailable"
          }
        ],
        next_cursor: options.body.cursor ? null : "next"
      })
    );
    const scope = { assistants: true, apps: false };
    let receipt = initialRollout(scope, null, "published");
    await advancePublishedBindings({
      skillId: "skill",
      revisionId: "published",
      adoption: null,
      scope,
      stopped: () => false,
      onProgress: (update) => {
        receipt = { ...receipt, ...update };
      }
    });
    expect(receipt).toMatchObject({
      assistants: {
        updated: 2,
        incompatible: 2,
        reasons: { activation_unavailable: 1, context_window: 1 }
      }
    });
  });

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
