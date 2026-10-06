// @vitest-environment jsdom
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { router } from "@/test/navigation";
import { renderInApp, testAppContext } from "@/test/render";
import { AccountProfile } from "./account-profile.client";

vi.mock("next/navigation", () => import("@/test/navigation"));
const setLocale = vi.hoisted(() => vi.fn(() => Promise.resolve()));
vi.mock("@/lib/i18n/actions", () => ({ setLocale }));

it("shows the current language as the selected value, named by the row title", async () => {
  const { container } = renderInApp(<AccountProfile />);

  const picker = screen.getByRole("combobox", { name: "Språk" });
  expect(picker.textContent).toContain("Svenska");
  await expectNoAxeViolations(container);
});

it("saves the chosen language and refreshes the page", async () => {
  renderInApp(<AccountProfile />);

  fireEvent.click(screen.getByRole("combobox", { name: "Språk" }));
  fireEvent.click(await screen.findByRole("option", { name: "English" }));

  await waitFor(() => expect(setLocale).toHaveBeenCalledWith("en"));
  await waitFor(() => expect(router.refresh).toHaveBeenCalled());
});

it("shows the frontend's and the backend's version", () => {
  renderInApp(<AccountProfile />, {
    appContext: testAppContext({ versions: { frontend: "0.1.0", backend: "2.3.0" } })
  });

  expect(screen.getByText("Frontend 0.1.0 · Backend 2.3.0")).toBeTruthy();
});
