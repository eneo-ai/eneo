import assert from "node:assert/strict";
import test from "node:test";

import { initSkills } from "./skills.js";

test("Skill catalogue keeps the bounded cursor page contract", async () => {
  const page = {
    items: [{ id: "skill-1", slug: "payroll" }],
    count: 1,
    limit: 25,
    next_cursor: "payroll",
    previous_cursor: null,
    total_count: 2
  };
  const calls = [];
  const skills = initSkills({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return page;
    }
  });

  const result = await skills.list({
    spaceId: "space-1",
    limit: 25,
    cursor: "benefits",
    query: "payroll"
  });

  assert.equal(result, page);
  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/spaces/{space_id}/skills/",
      request: {
        method: "get",
        params: {
          path: { space_id: "space-1" },
          query: { limit: 25, cursor: "benefits", q: "payroll" }
        }
      }
    }
  ]);
});

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

test("restore copies a selected revision through its scoped action route", async () => {
  const outcome = {
    revision: { id: "revision-4", revision_number: 4 },
    created: true,
    restored_from_revision_id: "revision-2",
    restored_from_revision_number: 2
  };
  const calls = [];
  const skills = initSkills({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return outcome;
    }
  });

  const result = await skills.restoreRevision({
    spaceId: "space-1",
    skillId: "skill-1",
    sourceRevisionId: "revision-2",
    reviewed_current_revision_id: "revision-3"
  });

  assert.equal(result, outcome);
  assert.deepEqual(calls, [
    {
      endpoint:
        "/api/v1/spaces/{space_id}/skills/{skill_id}/revisions/{source_revision_id}/restore/",
      request: {
        method: "post",
        params: {
          path: {
            space_id: "space-1",
            skill_id: "skill-1",
            source_revision_id: "revision-2"
          }
        },
        requestBody: {
          "application/json": {
            reviewed_current_revision_id: "revision-3"
          }
        }
      }
    }
  ]);
});

test("organisation restore sends the revision reviewed by the administrator", async () => {
  const calls = [];
  const response = { revision: { id: "revision-4" }, created: true };
  const skills = initSkills({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return response;
    }
  });

  const result = await skills.organization.restoreRevision({
    skillId: "skill-1",
    sourceRevisionId: "revision-2",
    reviewed_current_revision_id: "revision-3"
  });

  assert.equal(result, response);
  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/skills/organization/{skill_id}/revisions/{source_revision_id}/restore/",
      request: {
        method: "post",
        params: {
          path: {
            skill_id: "skill-1",
            source_revision_id: "revision-2"
          }
        },
        requestBody: {
          "application/json": {
            reviewed_current_revision_id: "revision-3"
          }
        }
      }
    }
  ]);
});

test("organisation publication sends the reviewed revision", async () => {
  const calls = [];
  const response = { id: "skill-1", publication_state: "published" };
  const skills = initSkills({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return response;
    }
  });

  const result = await skills.organization.publish({
    skillId: "skill-1",
    expected_revision_id: "revision-3"
  });

  assert.equal(result, response);
  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/skills/organization/{skill_id}/publish/",
      request: {
        method: "post",
        params: { path: { skill_id: "skill-1" } },
        requestBody: {
          "application/json": { expected_revision_id: "revision-3" }
        }
      }
    }
  ]);
});

test("organisation revision summaries use the shared cursor contract", async () => {
  const page = {
    items: [],
    count: 0,
    limit: 25,
    next_cursor: null,
    previous_cursor: null,
    total_count: 0
  };
  const calls = [];
  const skills = initSkills({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return page;
    }
  });

  const result = await skills.organization.listRevisionSummaries({
    skillId: "skill-1",
    limit: 25,
    cursor: "3"
  });

  assert.equal(result, page);
  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/skills/organization/{skill_id}/revisions/",
      request: {
        method: "get",
        params: {
          path: { skill_id: "skill-1" },
          query: { limit: 25, cursor: "3" }
        }
      }
    }
  ]);
});

test("catalogue reads use the tenant-scoped projection", async () => {
  const calls = [];
  const page = { items: [], limit: 25, next_cursor: null };
  const skills = initSkills({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return page;
    }
  });

  const result = await skills.catalogue.list({
    limit: 25,
    cursor: "payroll",
    search: "benefits"
  });

  assert.equal(result, page);
  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/skills/catalogue/",
      request: {
        method: "get",
        params: {
          query: { limit: 25, cursor: "payroll", search: "benefits" }
        }
      }
    }
  ]);
});
