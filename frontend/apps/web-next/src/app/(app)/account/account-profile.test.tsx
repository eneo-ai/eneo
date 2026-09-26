// @vitest-environment jsdom
import { screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext } from "@/test/render";
import { AccountProfile } from "./account-profile.client";

vi.mock("next/navigation", () => import("@/test/navigation"));

it("names the language picker by its row title (a combobox takes no name from its value)", async () => {
  const { container } = renderInApp(<AccountProfile />);

  expect(screen.getByRole("combobox", { name: "Språk" })).toBeTruthy();
  await expectNoAxeViolations(container);
});

it("shows the frontend's and the backend's version", () => {
  renderInApp(<AccountProfile />, {
    appContext: testAppContext({ versions: { frontend: "0.1.0", backend: "2.3.0" } })
  });

  expect(screen.getByText("Frontend 0.1.0 · Backend 2.3.0")).toBeTruthy();
});
