import { describe, expect, it } from "vitest";
import {
  DEFAULT_ADMIN_KEY_FILTERS,
  MAX_RESULT_LIMIT,
  RESULT_LIMITS,
  activeFilterCount,
  adminKeyListQuery,
  isFullApiKeySecret,
  secretSuffix
} from "./admin-key-filters";

const secret = `sk_${"a1b2c3d4".repeat(5)}`;

describe("adminKeyListQuery", () => {
  it("sends every filter the admin set", () => {
    expect(
      adminKeyListQuery(
        {
          search: " Diariet ",
          user: { id: "user-2", label: "kim@example.se" },
          userRelation: "creator",
          scopeType: "assistant",
          scopeId: "assistant-1",
          keyType: "pk_",
          expiresWithinDays: "14",
          limit: 25
        },
        "suspended",
        "cursor-2"
      )
    ).toEqual({
      cursor: "cursor-2",
      limit: 25,
      state: "suspended",
      scope_type: "assistant",
      scope_id: "assistant-1",
      key_type: "pk_",
      expires_within_days: 14,
      created_by_user_id: "user-2",
      user_relation: "creator",
      search: "Diariet"
    });
  });

  it("leaves out what is not set, every state, and a pasted whole key", () => {
    expect(
      adminKeyListQuery({ ...DEFAULT_ADMIN_KEY_FILTERS, search: secret }, "all", undefined)
    ).toEqual({
      cursor: undefined,
      limit: 100,
      state: undefined,
      scope_type: undefined,
      scope_id: undefined,
      key_type: undefined,
      expires_within_days: undefined,
      search: undefined
    });
  });
});

describe("a pasted whole key", () => {
  it("is told from a name or a suffix", () => {
    expect(isFullApiKeySecret(secret)).toBe(true);
    expect(isFullApiKeySecret("sk_a1b2c3d4")).toBe(false);
    expect(isFullApiKeySecret("Diariet integration with a long descriptive name")).toBe(false);
  });

  it("falls back to its last 8 characters", () => {
    expect(secretSuffix(secret)).toBe("a1b2c3d4");
  });
});

describe("activeFilterCount", () => {
  it("counts each narrowing filter, the state tab unless it shows every state", () => {
    expect(activeFilterCount(DEFAULT_ADMIN_KEY_FILTERS, "all")).toBe(0);
    expect(activeFilterCount(DEFAULT_ADMIN_KEY_FILTERS, "active")).toBe(1);
    expect(
      activeFilterCount(
        { ...DEFAULT_ADMIN_KEY_FILTERS, scopeType: "space", scopeId: "space-1", search: "x" },
        "all"
      )
    ).toBe(3);
  });
});

it("offers only page sizes the admin list endpoint accepts (1-200)", () => {
  expect(MAX_RESULT_LIMIT).toBe(200);
  expect(RESULT_LIMITS.every((limit) => limit >= 1 && limit <= MAX_RESULT_LIMIT)).toBe(true);
});
