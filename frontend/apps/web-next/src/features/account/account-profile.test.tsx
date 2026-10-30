// @vitest-environment jsdom
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { switchLocale } from "@/lib/i18n/switch-locale";
import { renderInApp, testAppContext } from "@/test/render";
import { AccountProfile } from "@/features/account/account-profile";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/lib/i18n/switch-locale", () => ({ switchLocale: vi.fn() }));

it("shows the current language as the selected value, named by the row title", async () => {
  const { container } = renderInApp(<AccountProfile />);

  const picker = screen.getByRole("combobox", { name: "Språk" });
  expect(picker.textContent).toContain("Svenska");
  await expectNoAxeViolations(container);
});

it("switches the chosen language through the document owner", async () => {
  renderInApp(<AccountProfile />);

  fireEvent.click(screen.getByRole("combobox", { name: "Språk" }));
  fireEvent.click(await screen.findByRole("option", { name: "English" }));

  await waitFor(() => expect(switchLocale).toHaveBeenCalledWith("en"));
});

it("shows the frontend's and the backend's version", () => {
  renderInApp(<AccountProfile />, {
    appContext: testAppContext({ versions: { frontend: "0.1.0", backend: "2.3.0" } })
  });

  expect(screen.getByText("Frontend 0.1.0 · Backend 2.3.0")).toBeTruthy();
});

it("shows a username that differs from the email", () => {
  renderInApp(<AccountProfile />, {
    appContext: testAppContext({ user: { username: "anna.legacy" } })
  });
  expect(screen.getByText("Användarnamn")).toBeTruthy();
  expect(screen.getByText("anna.legacy")).toBeTruthy();
});

it.each([null, "anna.lind@example.se"])(
  "does not repeat an absent or email username (%s)",
  (username) => {
    renderInApp(<AccountProfile />, { appContext: testAppContext({ user: { username } }) });
    expect(screen.queryByText("Användarnamn")).toBeNull();
  }
);
