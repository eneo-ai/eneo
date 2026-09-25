// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { ThemeProvider } from "next-themes";
import { afterEach, beforeAll, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { ThemeSwitcher } from "./theme-switcher";

const messages = { theme: "Tema", light: "Ljust", dark: "Mörkt", system: "System" };

beforeAll(() => {
  // Radix positions the menu with ResizeObserver, which jsdom lacks.
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  );
  // next-themes reads the system preference.
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: false,
    media: query,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {}
  }));
});

afterEach(cleanup);

function renderSwitcher() {
  return render(
    <NextIntlClientProvider locale="sv" messages={messages}>
      <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
        <ThemeSwitcher />
      </ThemeProvider>
    </NextIntlClientProvider>
  );
}

it("renders the theme menu trigger", async () => {
  const { container } = renderSwitcher();
  expect(screen.getByRole("button", { name: "Tema" })).toBeDefined();
  await expectNoAxeViolations(container);
});

it("opens from the keyboard and exposes the current theme as a checked radio item", async () => {
  renderSwitcher();
  fireEvent.keyDown(screen.getByRole("button", { name: "Tema" }), { key: "Enter" });

  const options = await screen.findAllByRole("menuitemradio");
  expect(options.map((option) => option.textContent)).toEqual(["Ljust", "Mörkt", "System"]);
  expect(screen.getByRole("menuitemradio", { name: "System" }).getAttribute("aria-checked")).toBe(
    "true"
  );
  // The menu is portalled to <body>, outside the render container.
  await expectNoAxeViolations(document.body);
});
