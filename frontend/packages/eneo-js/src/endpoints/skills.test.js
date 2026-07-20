import assert from "node:assert/strict";
import test from "node:test";

import { initSkills } from "./skills.js";

test("revision summaries use the bounded collection contract", async () => {
  const page = {
    items: [
      {
        id: "revision-2",
        skill_id: "skill-1",
        revision_number: 2,
        display_name: "Payroll",
        created_at: "2026-07-20T12:00:00Z"
      }
    ],
    count: 1,
    limit: 25,
    next_cursor: "2",
    previous_cursor: null,
    total_count: 3
  };
  const calls = [];
  const skills = initSkills({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return page;
    }
  });

  const result = await skills.listRevisionSummaries({
    spaceId: "space-1",
    skillId: "skill-1",
    limit: 25,
    cursor: "3"
  });

  assert.equal(result, page);
  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/spaces/{space_id}/skills/{skill_id}/revisions/",
      request: {
        method: "get",
        params: {
          path: { space_id: "space-1", skill_id: "skill-1" },
          query: { limit: 25, cursor: "3" }
        }
      }
    }
  ]);
  assert.equal("listRevisions" in skills, false);
});

test("one exact revision is loaded from the scoped member route", async () => {
  const revision = { id: "revision-2", instructions: "Full instructions" };
  const calls = [];
  const skills = initSkills({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return revision;
    }
  });

  const result = await skills.getRevision({
    spaceId: "space-1",
    skillId: "skill-1",
    revisionId: "revision-2"
  });

  assert.equal(result, revision);
  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/spaces/{space_id}/skills/{skill_id}/revisions/{revision_id}/",
      request: {
        method: "get",
        params: {
          path: {
            space_id: "space-1",
            skill_id: "skill-1",
            revision_id: "revision-2"
          }
        }
      }
    }
  ]);
});
