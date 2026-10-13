import { describe, expect, it } from "vitest";
import {
  buildLoginDiagnosticsUrl,
  diagnosticsFromUnknownError,
  loginDiagnosticMessageKey,
  loginDiagnosticsFromSearchParams
} from "./login-diagnostics";

describe("login diagnostics", () => {
  it("parses structured login params and legacy error params", () => {
    expect(
      loginDiagnosticsFromSearchParams(
        new URLSearchParams("message=oidc_callback_failed&detailCode=access_denied&correlation=c1")
      )
    ).toEqual({
      message: "oidc_callback_failed",
      info: undefined,
      detailCode: "access_denied",
      correlation: "c1",
      rawDetail: undefined
    });

    expect(loginDiagnosticsFromSearchParams(new URLSearchParams("error=access_denied"))).toEqual({
      message: "oidc_callback_failed",
      info: undefined,
      detailCode: "access_denied",
      correlation: undefined,
      rawDetail: undefined
    });
  });

  it("maps diagnostics to user-facing message keys", () => {
    expect(loginDiagnosticMessageKey({ detailCode: "access_denied" })).toBe("oidc_error_forbidden");
    expect(loginDiagnosticMessageKey({ detailCode: "unauthorized" })).toBe(
      "oidc_error_unauthorized"
    );
    expect(loginDiagnosticMessageKey({ detailCode: "server_error" })).toBe("oidc_error_generic");
  });

  it("builds bounded diagnostic redirect URLs", () => {
    const url = buildLoginDiagnosticsUrl("/login/failed", "https://app.example", {
      message: "oidc_callback_failed",
      correlation: "corr",
      rawDetail: "x".repeat(1200)
    });
    expect(url.pathname).toBe("/login/failed");
    expect(url.searchParams.get("correlation")).toBe("corr");
    expect(url.searchParams.get("rawDetail")).toHaveLength(1000);
  });

  it("extracts detail from unknown OIDC errors without throwing", () => {
    expect(
      diagnosticsFromUnknownError({
        error: "invalid_grant",
        error_description: "Bad code"
      })
    ).toEqual({ detailCode: "invalid_grant", rawDetail: "Bad code" });
  });
});
