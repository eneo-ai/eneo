import { describe, expect, test } from "vitest";
import { passwordChangeUrl, readPasswordChangeReason } from "./passwordChangeRequired";

describe("forced password change helpers", () => {
  test("keeps the interrupted destination so the user lands back after signing in again", () => {
    expect(passwordChangeUrl(new URL("https://eneo.example/spaces/abc?tab=2"))).toBe(
      "/password-change?next=%2Fspaces%2Fabc%3Ftab%3D2"
    );
  });

  test("drops a pointless destination", () => {
    expect(passwordChangeUrl(new URL("https://eneo.example/"))).toBe("/password-change");
    expect(passwordChangeUrl(new URL("https://eneo.example/password-change?next=%2F"))).toBe(
      "/password-change"
    );
    expect(passwordChangeUrl()).toBe("/password-change");
  });

  test("only a change_required status forces the page; an unknown reason reads as admin-set", () => {
    expect(readPasswordChangeReason({ change_required: true, reason: "admin_set" })).toBe(
      "admin_set"
    );
    expect(readPasswordChangeReason({ change_required: true, reason: "expired" })).toBe("expired");
    expect(readPasswordChangeReason({ change_required: true, reason: "later" })).toBe("admin_set");
    expect(readPasswordChangeReason({ change_required: false, reason: "expired" })).toBeNull();
    expect(readPasswordChangeReason(null)).toBeNull();
    expect(readPasswordChangeReason("yes")).toBeNull();
  });
});
