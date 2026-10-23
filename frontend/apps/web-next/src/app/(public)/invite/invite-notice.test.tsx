// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { InviteNotice } from "./invite-notice";

afterEach(cleanup);

it("explains that invitations are handled on the login page and links there", async () => {
  const { container } = renderInApp(<InviteNotice />);

  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Inbjudan till Eneo");
  expect(screen.getByText(/hanteras på inloggningssidan/)).toBeTruthy();
  expect(screen.getByRole("link", { name: "Gå till inloggningen" }).getAttribute("href")).toBe(
    "/login"
  );
  await expectNoAxeViolations(container, {});
});
