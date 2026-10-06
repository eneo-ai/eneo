import * as client from "openid-client";
import { describe, expect, it } from "vitest";
import { accessTokenExpiry, startAuthorization } from "./oidc";

const serverMetadata = {
  issuer: "https://idp.example.com",
  authorization_endpoint: "https://idp.example.com/authorize",
  token_endpoint: "https://idp.example.com/token"
};

describe("startAuthorization", () => {
  it("builds an authorize URL with PKCE, state and nonce", async () => {
    const config = new client.Configuration(serverMetadata, "client-id", "client-secret");
    const start = await startAuthorization(config);

    const url = new URL(start.url);
    expect(url.origin + url.pathname).toBe("https://idp.example.com/authorize");
    expect(url.searchParams.get("client_id")).toBe("client-id");
    expect(url.searchParams.get("redirect_uri")).toBe("http://localhost:3100/auth/callback");
    expect(url.searchParams.get("code_challenge_method")).toBe("S256");
    expect(url.searchParams.get("code_challenge")).toBeTruthy();
    expect(url.searchParams.get("state")).toBe(start.state);
    expect(url.searchParams.get("nonce")).toBe(start.nonce);
    expect(url.searchParams.get("scope")).toContain("openid");
    expect(start.verifier.length).toBeGreaterThanOrEqual(43);
  });
});

describe("accessTokenExpiry", () => {
  it("adds expires_in to now", () => {
    expect(accessTokenExpiry(120, 1_000_000)).toBe(1_000_120);
  });

  it("defaults to 5 minutes when the IdP omits expires_in", () => {
    expect(accessTokenExpiry(undefined, 1_000_000)).toBe(1_000_300);
  });
});
