import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { createEneo } from "../eneo.js";
import { initSpaces } from "./spaces.js";

const SCHEMA = readFileSync(new URL("../types/schema.d.ts", import.meta.url), "utf8");

/**
 * The typed fetch only accepts schema paths when a caller type-checks; these
 * files are plain JS, so hold every recorded call to the generated schema here.
 * @param {{endpoint: string, request: unknown}[]} calls
 */
function assertSchemaOperations(calls) {
  for (const { endpoint, request } of calls) {
    const method = /** @type {{method: string}} */ (request).method;
    const start = SCHEMA.indexOf(`\n  "${endpoint}": {`);
    assert.notEqual(start, -1, `${endpoint} is not a path in schema.d.ts`);
    const block = SCHEMA.slice(start, SCHEMA.indexOf("\n  };", start));
    assert.match(block, new RegExp(`\\n    ${method}: operations\\[`), `${method} ${endpoint}`);
  }
}

/**
 * One top-level entry of the generated `components["schemas"]`, up to the next.
 * @param {string} name
 */
function schemaEntry(name) {
  const start = SCHEMA.indexOf(`\n    ${name}:`);
  assert.notEqual(start, -1, `${name} is not a schema in schema.d.ts`);
  const rest = SCHEMA.slice(start + 1);
  const next = rest.search(/\n {4}(?:\/\*\*|[A-Za-z_])/);
  return next === -1 ? rest : rest.slice(0, next);
}

const SPACE_ID = "0b5f6c43-5b8e-4a1e-9d65-1f1c2d3e4f50";
const USER_ID = "6f1d2c3b-4a59-4e8f-9d7c-6b5a4f3e2d10";
const GROUP_ID = "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d";

function recordingSpaces() {
  /** @type {{endpoint: string, request: unknown}[]} */
  const calls = [];
  const spaces = initSpaces(
    /** @type {any} */ ({
      fetch: async (/** @type {string} */ endpoint, /** @type {unknown} */ request) => {
        calls.push({ endpoint, request });
        return { endpoint };
      }
    })
  );
  return { spaces, calls };
}

test("createEneo exposes space oversight for organisation admins", () => {
  const eneo = createEneo({ baseUrl: "https://example.test" });

  for (const call of [
    eneo.spaces.admin.list,
    eneo.spaces.admin.get,
    eneo.spaces.admin.join,
    eneo.spaces.admin.leave,
    eneo.spaces.admin.members.add,
    eneo.spaces.admin.members.update,
    eneo.spaces.admin.members.remove,
    eneo.spaces.admin.groupMembers.add,
    eneo.spaces.admin.groupMembers.update,
    eneo.spaces.admin.groupMembers.remove
  ]) {
    assert.equal(typeof call, "function");
  }
});

test("oversight reads return the whole response, not only its items", async () => {
  const { spaces, calls } = recordingSpaces();

  // widget_requests travels next to items, so list() must not unwrap.
  assert.deepEqual(await spaces.admin.list(), { endpoint: "/api/v1/admin/spaces/" });
  await spaces.admin.get({ id: SPACE_ID });

  assert.deepEqual(calls, [
    { endpoint: "/api/v1/admin/spaces/", request: { method: "get" } },
    {
      endpoint: "/api/v1/admin/spaces/{space_id}/",
      request: { method: "get", params: { path: { space_id: SPACE_ID } } }
    }
  ]);
  assertSchemaOperations(calls);
});

test("join sends the role and reason, and leave sends no body", async () => {
  const { spaces, calls } = recordingSpaces();

  await spaces.admin.join({
    spaceId: SPACE_ID,
    role: "viewer",
    reason: "Ärende KS 2026/123 – kontroll av underlag"
  });
  await spaces.admin.leave({ spaceId: SPACE_ID });

  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/admin/spaces/{space_id}/join/",
      request: {
        method: "post",
        params: { path: { space_id: SPACE_ID } },
        requestBody: {
          "application/json": {
            role: "viewer",
            reason: "Ärende KS 2026/123 – kontroll av underlag"
          }
        }
      }
    },
    {
      endpoint: "/api/v1/admin/spaces/{space_id}/leave/",
      request: { method: "post", params: { path: { space_id: SPACE_ID } } }
    }
  ]);
  assertSchemaOperations(calls);
});

test("member changes address the user and send only what the route accepts", async () => {
  const { spaces, calls } = recordingSpaces();

  await spaces.admin.members.add({ spaceId: SPACE_ID, userId: USER_ID, role: "admin" });
  await spaces.admin.members.update({ spaceId: SPACE_ID, userId: USER_ID, role: "editor" });
  await spaces.admin.members.remove({ spaceId: SPACE_ID, userId: USER_ID });

  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/admin/spaces/{space_id}/members/",
      request: {
        method: "post",
        params: { path: { space_id: SPACE_ID } },
        requestBody: { "application/json": { user_id: USER_ID, role: "admin" } }
      }
    },
    {
      endpoint: "/api/v1/admin/spaces/{space_id}/members/{user_id}/",
      request: {
        method: "patch",
        params: { path: { space_id: SPACE_ID, user_id: USER_ID } },
        requestBody: { "application/json": { role: "editor" } }
      }
    },
    {
      endpoint: "/api/v1/admin/spaces/{space_id}/members/{user_id}/",
      request: {
        method: "delete",
        params: { path: { space_id: SPACE_ID, user_id: USER_ID } }
      }
    }
  ]);
  assertSchemaOperations(calls);
});

test("group member changes address the group", async () => {
  const { spaces, calls } = recordingSpaces();

  await spaces.admin.groupMembers.add({ spaceId: SPACE_ID, groupId: GROUP_ID, role: "viewer" });
  await spaces.admin.groupMembers.update({ spaceId: SPACE_ID, groupId: GROUP_ID, role: "admin" });
  await spaces.admin.groupMembers.remove({ spaceId: SPACE_ID, groupId: GROUP_ID });

  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/admin/spaces/{space_id}/group-members/",
      request: {
        method: "post",
        params: { path: { space_id: SPACE_ID } },
        requestBody: { "application/json": { group_id: GROUP_ID, role: "viewer" } }
      }
    },
    {
      endpoint: "/api/v1/admin/spaces/{space_id}/group-members/{group_id}/",
      request: {
        method: "patch",
        params: { path: { space_id: SPACE_ID, group_id: GROUP_ID } },
        requestBody: { "application/json": { role: "admin" } }
      }
    },
    {
      endpoint: "/api/v1/admin/spaces/{space_id}/group-members/{group_id}/",
      request: {
        method: "delete",
        params: { path: { space_id: SPACE_ID, group_id: GROUP_ID } }
      }
    }
  ]);
  assertSchemaOperations(calls);
});

test("the schema carries the oversight fields the web app reads", () => {
  const assistant = schemaEntry("AdminSpaceAssistant");
  // Every widget of an assistant, not the last one by name.
  assert.match(assistant, /\n {6}widgets: components\["schemas"\]\["AdminSpaceWidgetRef"\]\[\];/);
  assert.doesNotMatch(assistant, /\n {6}widget\??:/);
  // Creation and change times are days, never a time of day.
  for (const name of ["AdminSpaceAssistant", "AdminSpaceDetail"]) {
    assert.match(
      schemaEntry(name),
      /Format: date\n[^\n]*\n {7}\*\/\n {6}updated_at: string;/,
      name
    );
  }
  for (const name of ["AdminSpaceListItem", "AdminSpaceDetail"]) {
    assert.match(
      schemaEntry(name),
      /Format: date\n[^\n]*\n {7}\*\/\n {6}created_at: string;/,
      name
    );
  }

  // Each count is withheld on its own; widget questions until a widget was live.
  const usage = schemaEntry("AdminSpaceUsage");
  for (const field of ["questions", "app_runs", "active_users", "widget_questions"]) {
    assert.match(usage, new RegExp(`\\n {6}${field}\\?: number \\| null;`), field);
  }

  // A nameless integration source says what it covers instead.
  for (const name of ["OversightKnowledgeRef", "AdminSpaceKnowledgeSource"]) {
    assert.match(
      schemaEntry(name),
      /\n {6}integration_item\?: \("site" \| "folder" \| "file"\) \| null;/,
      name
    );
  }

  // Members see oversight joins after the administrator has left.
  assert.match(
    schemaEntry("SpacePublic"),
    /\n {6}oversight_visits\?: components\["schemas"\]\["SpaceOversightVisit"\]\[\];/
  );
  assert.match(schemaEntry("SpaceOversightVisit"), /\n {6}left_at\?: string \| null;/);

  // Another tenant admin must join; group membership changes are always logged.
  assert.match(schemaEntry("ErrorCodes"), /\| 9068/);
  assert.match(schemaEntry("ActionType"), /\| "user_group_member_added"/);
  assert.match(schemaEntry("ActionType"), /\| "user_group_member_removed"/);
});
