import { describe, expect, test } from "vitest";
import { load } from "./+page.server";

describe("login failure retry", () => {
  test("preserves a safe local resume destination", async () => {
    const destination = "/module-login?state=opaque%2526value";
    const url = new URL("https://eneo.example/login/failed?message=oidc_login_error");
    url.searchParams.set("next", destination);

    const result = await load({ url } as never);

    const retry = new URL(result.retryUrl, "https://eneo.example");
    expect(retry.pathname).toBe("/login");
    expect(retry.searchParams.get("next")).toBe(destination);
  });

  test("never reflects an external retry destination", async () => {
    const url = new URL(
      "https://eneo.example/login/failed?message=oidc_login_error&next=//evil.example"
    );

    const result = await load({ url } as never);

    const retry = new URL(result.retryUrl, "https://eneo.example");
    expect(retry.origin).toBe("https://eneo.example");
    expect(retry.pathname).toBe("/login");
    expect(retry.searchParams.get("next")).not.toBe("//evil.example");
  });
});
