// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { ThemeProvider } from "next-themes";
import { afterEach, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { switchLocale } from "@/lib/i18n/switch-locale";
import { renderInApp } from "@/test/render";
import { AccountAppearance } from "./account-appearance.client";

vi.mock("next/navigation", () => import("@/test/navigation"));
vi.mock("@/lib/i18n/switch-locale", () => ({ switchLocale: vi.fn() }));

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  document.documentElement.className = "";
});

/** What Astryx's polite live region has said (useAnnounce). */
const announced = () =>
  [...document.querySelectorAll("[aria-live]")].map((region) => region.textContent).join(" ");

/** The theme's options are buttons (aria-checked), the languages' native radios. */
const isChecked = (radio: HTMLElement) =>
  radio.getAttribute("aria-checked") === "true" || (radio as HTMLInputElement).checked;

function renderAppearance() {
  return renderInApp(
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
      <AccountAppearance />
    </ThemeProvider>
  );
}

it("sets the theme at once, says so, and needs no save", async () => {
  const { container } = renderAppearance();
  const system = await screen.findByRole("radio", { name: "System" });
  await waitFor(() => expect(isChecked(system)).toBe(true));
  expect(screen.getByText("System följer inställningen på din enhet.")).toBeTruthy();

  fireEvent.click(screen.getByRole("radio", { name: "Mörkt" }));
  await waitFor(() => expect(document.documentElement.classList.contains("dark")).toBe(true));
  expect(isChecked(screen.getByRole("radio", { name: "Mörkt" }))).toBe(true);
  await waitFor(() => expect(announced()).toContain("Tema: Mörkt"));
  expect(screen.queryByRole("button", { name: /Spara/ })).toBeNull();
  await expectNoAxeViolations(container);
});

it("switches the document language, each option named in its own", async () => {
  renderAppearance();
  const english = screen.getByRole("radio", { name: "English" });
  expect(screen.getByText("English").closest("[lang='en']")).toBeTruthy();
  expect(isChecked(screen.getByRole("radio", { name: "Svenska" }))).toBe(true);

  fireEvent.click(english);
  expect(switchLocale).toHaveBeenCalledWith("en");
});
