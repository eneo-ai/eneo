import { describe, expect, test, vi } from "vitest";
import { load } from "./+page";

function eventWithPolicy(policy: unknown) {
  return {
    parent: async () => ({
      eneo: {
        users: {
          list: async () => ({ items: [], metadata: null }),
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
