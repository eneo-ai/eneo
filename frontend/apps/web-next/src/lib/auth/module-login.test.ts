import { describe, expect, it } from "vitest";
import {
  loginPathToResume,
  moduleLoginFailurePath,
  moduleLoginFailureReason,
  moduleLoginResumePath,
  parseModuleLoginRequest,
  redirectTargetFromBody,
  ticketOutcome,
  validatedRedirectTarget
} from "./module-login";

const VALID = "module_key=reports&redirect_uri=https%3A%2F%2Freports.example.se%2Fcb&state=abc";

describe("parseModuleLoginRequest", () => {
  it("accepts the three parameters, each once", () => {
    expect(parseModuleLoginRequest(new URLSearchParams(VALID))).toEqual({
      moduleKey: "reports",
      redirectUri: "https://reports.example.se/cb",
      state: "abc"
    });
  });

  it.each([
    ["a missing parameter", "module_key=reports&redirect_uri=https%3A%2F%2Fm.example"],
    ["a blank parameter", "module_key=%20&redirect_uri=https%3A%2F%2Fm.example&state=abc"],
    ["a repeated parameter", `${VALID}&state=def`],
    ["an unknown parameter", `${VALID}&token=leak`],
    ["no parameters", ""]
  ])("rejects %s", (_, query) => {
    expect(parseModuleLoginRequest(new URLSearchParams(query))).toBeNull();
  });
});

describe("resume and failure paths", () => {
  it("resumes the hand-off with its parameters after login", () => {
    const resume = moduleLoginResumePath(new URL(`http://localhost:3100/module-login?${VALID}`));
    expect(resume).toBe(`/module-login?${VALID}`);
    const login = loginPathToResume(resume);
    expect(login.startsWith("/login?next=")).toBe(true);
    expect(new URLSearchParams(login.slice("/login?".length)).get("next")).toBe(resume);
  });

  it("names the failure reason on the failed page", () => {
    expect(moduleLoginFailurePath("module_unavailable")).toBe(
      "/module-login/failed?reason=module_unavailable"
    );
  });

  it("falls back to invalid_request for unknown or missing reasons", () => {
    expect(moduleLoginFailureReason("service_unavailable")).toBe("service_unavailable");
    expect(moduleLoginFailureReason("module_unavailable")).toBe("module_unavailable");
    expect(moduleLoginFailureReason("other")).toBe("invalid_request");
    expect(moduleLoginFailureReason(undefined)).toBe("invalid_request");
    expect(moduleLoginFailureReason(["service_unavailable"])).toBe("invalid_request");
  });
});

describe("ticketOutcome", () => {
  it("maps the backend status the way the SvelteKit route does", () => {
    expect(ticketOutcome(201)).toEqual({ kind: "issued" });
    expect(ticketOutcome(200)).toEqual({ kind: "issued" });
    expect(ticketOutcome(401)).toEqual({ kind: "login" });
    expect(ticketOutcome(422)).toEqual({ kind: "failure", reason: "invalid_request" });
    for (const status of [400, 403, 404]) {
      expect(ticketOutcome(status)).toEqual({ kind: "failure", reason: "module_unavailable" });
    }
    for (const status of [500, 502, 503, 302]) {
      expect(ticketOutcome(status)).toEqual({ kind: "failure", reason: "service_unavailable" });
    }
  });
});

describe("validatedRedirectTarget", () => {
  it("returns an http(s) target exactly as received", () => {
    const target = "https://reports.example.se/cb?ticket=a%20b&state=abc#x";
    expect(validatedRedirectTarget(target)).toBe(target);
    expect(validatedRedirectTarget("http://localhost:4000/cb?ticket=t")).toBe(
      "http://localhost:4000/cb?ticket=t"
    );
  });

  it.each([
    ["javascript:alert(1)"],
    ["data:text/html,hi"],
    ["https://user:pw@m.example/cb"],
    ["https://user@m.example/cb"],
    ["/relative/path"],
    ["not a url"],
    [""],
    [42],
    [null]
  ])("rejects %j", (value) => {
    expect(validatedRedirectTarget(value)).toBeNull();
  });
});

describe("redirectTargetFromBody", () => {
  it("reads redirect_target from an object body", () => {
    expect(redirectTargetFromBody({ redirect_target: "https://m.example/cb?ticket=t" })).toBe(
      "https://m.example/cb?ticket=t"
    );
  });

  it("rejects bodies without a usable target", () => {
    expect(redirectTargetFromBody(null)).toBeNull();
    expect(redirectTargetFromBody("https://m.example/cb")).toBeNull();
    expect(redirectTargetFromBody({})).toBeNull();
    expect(redirectTargetFromBody({ redirect_target: "ftp://m.example" })).toBeNull();
  });
});
