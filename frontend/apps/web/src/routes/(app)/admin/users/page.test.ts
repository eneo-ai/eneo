import { describe, expect, test, vi } from "vitest";
import { load } from "./+page";

function eventWithPolicy(policy: unknown) {
  return {
    parent: async () => ({
      eneo: {
        users: {
          list: async () => ({
            items: [],
            metadata: {
              page: 1,
              page_size: 100,
              total_count: 0,
              total_pages: 0,
              has_next: false,
              has_previous: false,
              counts: { active: 0, inactive: 0 }
            }
          }),
          passwordPolicy: async () => policy
        }
      }
    }),
    depends: vi.fn(),
    url: new URL("https://eneo.example/admin/users")
  };
}

describe("admin password policy loading", () => {
  test("loads the local policy independently of the administrator's own password provider", async () => {
    const result = await load(
      eventWithPolicy({
        min_length: 20,
        max_bytes: 64,
        requires_uppercase: true,
        requires_lowercase: false,
        requires_number: true,
        requires_symbol: false
      }) as never
    );
    expect(result).toMatchObject({
      passwordCapability: {
        source: "eneo",
        policy: {
          minLength: 20,
          maxBytes: 64,
          requiresUppercase: true,
          requiresLowercase: false,
          requiresNumber: true,
          requiresSymbol: false
        }
      }
    });
  });

  test("fails instead of displaying guessed rules when the policy is missing", async () => {
    await expect(load(eventWithPolicy(null) as never)).rejects.toMatchObject({ status: 503 });
  });
});

const policy = {
  min_length: 8,
  max_bytes: 72,
  requires_uppercase: false,
  requires_lowercase: false,
  requires_number: false,
  requires_symbol: false
};
const metadata = {
  page: 1,
  total_pages: 1,
  total_count: 1,
  page_size: 100,
  has_next: false,
  has_previous: false,
  counts: { active: 20000, inactive: 1 }
};
function makeEvent(search: string) {
  const users = [{ id: "inactive-user", state: "inactive" }];
  const list = vi.fn().mockResolvedValue({ items: users, metadata });
  const event = {
    url: new URL(`https://eneo.test/admin/users${search}`),
    depends: vi.fn(),
    parent: vi
      .fn()
      .mockResolvedValue({ eneo: { users: { list, passwordPolicy: async () => policy } } })
  };
  return { event: event as unknown as Parameters<typeof load>[0], list, users };
}

test("inactive status, role and both searches are passed to the server together", async () => {
  const { event, list, users } = makeEvent(
    "?tab=inactive&search=anna&search_name=smith&role_id=role-1"
  );
  const result = await load(event);
  expect(list).toHaveBeenCalledWith({
    includeDetails: true,
    state_filter: "inactive",
    search_email: "anna",
    search_name: "smith",
    role_id: "role-1",
    page: 1
  });
  expect(result).toMatchObject({ users, pagination: metadata, counts: metadata.counts });
});

test("a mutation emptying the last page redirects to a reachable page, keeping filters", async () => {
  const { event } = makeEvent("?tab=inactive&page=2&role_id=role-1");
  await expect(load(event)).rejects.toMatchObject({
    status: 307,
    location: "/admin/users?tab=inactive&role_id=role-1"
  });
});

test("short search links fail before querying the API", async () => {
  const { event, list } = makeEvent("?search=an");
  await expect(load(event)).rejects.toMatchObject({ status: 400 });
  expect(list).not.toHaveBeenCalled();
});
