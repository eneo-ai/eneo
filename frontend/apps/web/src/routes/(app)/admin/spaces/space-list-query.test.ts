import type { AdminSpaceListItem } from "@eneo/eneo-js";
import { describe, expect, test } from "vitest";
import {
  DEFAULT_QUERY,
  PAGE_SIZE,
  clampPage,
  filterSpaces,
  isFiltered,
  membershipCounts,
  nextSort,
  pageCount,
  readSpaceListQuery,
  sortSpaces,
  spaceListQueryString,
  type SpaceListQuery
} from "./space-list-query";

const read = (search: string) =>
  readSpaceListQuery(new URL(`https://eneo.example/admin/spaces${search}`));

function space(
  name: string,
  patch: Partial<AdminSpaceListItem> & {
    role?: AdminSpaceListItem["viewer_membership"]["role"];
  } = {}
): AdminSpaceListItem {
  const { role = null, ...rest } = patch;
  return {
    id: `id-${name}`,
    name,
    description: null,
    created_at: "2026-01-01T00:00:00Z",
    member_count: 1,
    group_count: 0,
    admins: { manageable: true, count: 1, principals: [{ kind: "user", id: "a", name: "Ada" }] },
    resources: { assistants: 0, apps: 0, group_chats: 0, knowledge_sources: 0 },
    widgets: { active: 0, paused: 0, draft: 0, awaiting_activation: 0 },
    last_activity: "none",
    viewer_membership: { role, via_group_only: false },
    attention: [],
    ...rest
  };
}

const query = (patch: Partial<SpaceListQuery> = {}): SpaceListQuery => ({
  ...DEFAULT_QUERY,
  ...patch
});

describe("reading the list's URL", () => {
  test("an empty URL is the default: every space by name, A to Ö, page one", () => {
    expect(read("")).toEqual(DEFAULT_QUERY);
    expect(DEFAULT_QUERY).toEqual({
      q: "",
      membership: "all",
      show: "all",
      sort: "name",
      dir: "asc",
      page: 1
    });
  });

  test("reads every parameter", () => {
    expect(
      read("?q=+ekonomi+&membership=not_member&show=no_admin&sort=members&dir=asc&page=3")
    ).toEqual({
      q: "ekonomi",
      membership: "not_member",
      show: "no_admin",
      sort: "members",
      dir: "asc",
      page: 3
    });
  });

  test("falls back to the defaults for invalid values", () => {
    expect(read("?membership=owner&show=everything&sort=size&dir=up&page=-2")).toEqual(
      DEFAULT_QUERY
    );
    expect(read("?page=2.5").page).toBe(1);
    expect(read("?page=abc").page).toBe(1);
  });

  test("a sort column without a direction uses that column's natural direction", () => {
    expect(read("?sort=members").dir).toBe("desc");
    expect(read("?sort=activity").dir).toBe("desc");
    expect(read("?sort=name").dir).toBe("asc");
  });
});

describe("writing the list's URL", () => {
  test("leaves out every default, so the plain list has a plain URL", () => {
    expect(spaceListQueryString(DEFAULT_QUERY)).toBe("");
    expect(spaceListQueryString(query({ sort: "members", dir: "desc" }))).toBe("?sort=members");
  });

  test("round-trips a full query", () => {
    const full = query({
      q: "hr",
      membership: "member",
      show: "widget_request",
      sort: "activity",
      dir: "asc",
      page: 2
    });
    const search = spaceListQueryString(full, { page: 2 });
    expect(search).toBe("?q=hr&membership=member&show=widget_request&sort=activity&dir=asc&page=2");
    expect(read(search)).toEqual(full);
  });

  test("a change goes back to page one unless it names a page", () => {
    const onPage3 = query({ page: 3 });
    expect(spaceListQueryString(onPage3, { show: "attention" })).toBe("?show=attention");
    expect(spaceListQueryString(onPage3, { page: 4 })).toBe("?page=4");
  });

  test("trims the search and drops it when blank", () => {
    expect(spaceListQueryString(query({ q: "  " }))).toBe("");
    expect(spaceListQueryString(query({ q: " it " }))).toBe("?q=it");
  });
});

describe("sorting", () => {
  test("a new column starts in its natural direction, the same column flips", () => {
    expect(nextSort(DEFAULT_QUERY, "members")).toEqual({ sort: "members", dir: "desc" });
    expect(nextSort(DEFAULT_QUERY, "name")).toEqual({ sort: "name", dir: "desc" });
    expect(nextSort(query({ sort: "activity", dir: "desc" }), "activity")).toEqual({
      sort: "activity",
      dir: "asc"
    });
  });

  const collator = new Intl.Collator("sv-SE");
  const items = [
    space("Östersund", { member_count: 5, last_activity: "past_month" }),
    space("Ekonomi", { member_count: 40, last_activity: "none" }),
    space("Ärenden", { member_count: 5, last_activity: "past_week" }),
    space("Arkiv", { member_count: 2, last_activity: "older" })
  ];
  const names = (list: AdminSpaceListItem[]) => list.map((item) => item.name);

  test("by name in Swedish order", () => {
    expect(names(sortSpaces(items, "name", "asc", collator))).toEqual([
      "Arkiv",
      "Ekonomi",
      "Ärenden",
      "Östersund"
    ]);
    expect(names(sortSpaces(items, "name", "desc", collator))[0]).toBe("Östersund");
  });

  test("by members, ties by name", () => {
    expect(names(sortSpaces(items, "members", "desc", collator))).toEqual([
      "Ekonomi",
      "Ärenden",
      "Östersund",
      "Arkiv"
    ]);
  });

  test("by activity bucket, most recent first when descending", () => {
    expect(names(sortSpaces(items, "activity", "desc", collator))).toEqual([
      "Ärenden",
      "Östersund",
      "Arkiv",
      "Ekonomi"
    ]);
  });

  test("never changes the input", () => {
    const before = names(items);
    sortSpaces(items, "members", "desc", collator);
    expect(names(items)).toEqual(before);
  });
});

describe("filtering", () => {
  const items = [
    space("Ekonomi", { description: "Budget och prognoser", role: "viewer" }),
    space("HR", {
      attention: ["no_admin"],
      admins: { manageable: false, count: 0, principals: [] }
    }),
    space("Webb", { attention: ["widget_activation_requested"], role: "admin" }),
    space("IT-stöd", {
      admins: {
        manageable: true,
        count: 1,
        principals: [{ kind: "group", id: "g", name: "Servicedesk" }]
      }
    })
  ];
  const names = (list: AdminSpaceListItem[]) => list.map((item) => item.name);

  test("searches names, descriptions and administrators, ignoring case", () => {
    expect(names(filterSpaces(items, query({ q: "BUDGET" })))).toEqual(["Ekonomi"]);
    expect(names(filterSpaces(items, query({ q: "servicedesk" })))).toEqual(["IT-stöd"]);
    expect(names(filterSpaces(items, query({ q: "  " })))).toHaveLength(4);
  });

  test("keeps membership and 'Visa' apart, so both can apply at once", () => {
    expect(names(filterSpaces(items, query({ membership: "member" })))).toEqual([
      "Ekonomi",
      "Webb"
    ]);
    expect(names(filterSpaces(items, query({ show: "attention" })))).toEqual(["HR", "Webb"]);
    expect(names(filterSpaces(items, query({ show: "no_admin" })))).toEqual(["HR"]);
    expect(names(filterSpaces(items, query({ show: "widget_request" })))).toEqual(["Webb"]);
    expect(
      names(filterSpaces(items, query({ membership: "not_member", show: "attention" })))
    ).toEqual(["HR"]);
  });

  test("counts each membership option under the other filters", () => {
    expect(membershipCounts(items, DEFAULT_QUERY)).toEqual({ all: 4, member: 2, not_member: 2 });
    expect(membershipCounts(items, query({ show: "attention", membership: "member" }))).toEqual({
      all: 2,
      member: 1,
      not_member: 1
    });
  });

  test("knows when the list is narrowed", () => {
    expect(isFiltered(DEFAULT_QUERY)).toBe(false);
    expect(isFiltered(query({ sort: "members", page: 3 }))).toBe(false);
    expect(isFiltered(query({ q: "x" }))).toBe(true);
    expect(isFiltered(query({ membership: "member" }))).toBe(true);
    expect(isFiltered(query({ show: "no_admin" }))).toBe(true);
  });
});

describe("paging", () => {
  test(`splits into pages of ${PAGE_SIZE} and keeps the page in range`, () => {
    expect(pageCount(0)).toBe(1);
    expect(pageCount(PAGE_SIZE)).toBe(1);
    expect(pageCount(PAGE_SIZE + 1)).toBe(2);
    expect(clampPage(5, PAGE_SIZE + 1)).toBe(2);
    expect(clampPage(0, 10)).toBe(1);
  });
});
