// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { ModuleLoginFailed } from "./module-login-failed";

afterEach(cleanup);

describe("ModuleLoginFailed", () => {
  it("names the failure, explains what to do and leads back into Eneo", async () => {
    const { container } = renderInApp(<ModuleLoginFailed reason="invalid_request" />);

    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Modulen kunde inte öppnas");
    expect(screen.getByText(/Gå tillbaka till modulen och försök igen/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Tillbaka till Eneo" }).getAttribute("href")).toBe(
      "/spaces/personal/chat"
    );
    await expectNoAxeViolations(container, {});
  });

  it.each([
    ["module_unavailable", /inte tillgänglig för din organisation/],
    ["service_unavailable", /Försök igen senare/]
  ] as const)("explains the %s reason", (reason, description) => {
    renderInApp(<ModuleLoginFailed reason={reason} />);
    expect(screen.getByText(description)).toBeTruthy();
  });
});
