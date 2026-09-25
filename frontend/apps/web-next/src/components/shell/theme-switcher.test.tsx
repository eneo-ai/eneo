// @vitest-environment jsdom
import { DropdownMenu } from "@astryxdesign/core/DropdownMenu";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { ThemeProvider } from "next-themes";
import { afterEach, beforeEach, expect, it } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { installBrowserMocks } from "./test-support";
import { ThemeSubMenu } from "./theme-switcher";

const messages = { theme: "Tema", light: "Ljust", dark: "Mörkt", system: "System" };

beforeEach(() => installBrowserMocks());
afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

function renderMenu() {
  return render(
    <NextIntlClientProvider locale="sv" messages={messages}>
      <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
        <DropdownMenu button={{ label: "Meny" }}>
          <ThemeSubMenu />
        </DropdownMenu>
      </ThemeProvider>
    </NextIntlClientProvider>
  );
}

async function openThemeSubMenu() {
  fireEvent.click(screen.getByRole("button", { name: "Meny" }));
  fireEvent.click(await screen.findByRole("menuitem", { name: /Tema/ }));
  return screen.findAllByRole("menuitemradio");
}

it("exposes the colour modes as radio items with the current one checked", async () => {
  renderMenu();
  const options = await openThemeSubMenu();
  expect(options.map((option) => option.textContent)).toEqual(["Ljust", "Mörkt", "System"]);
  await waitFor(() =>
    expect(screen.getByRole("menuitemradio", { name: "System" }).getAttribute("aria-checked")).toBe(
      "true"
    )
  );
  await expectNoAxeViolations(document.body);
});

it("switches the colour mode", async () => {
  renderMenu();
  await openThemeSubMenu();
  fireEvent.click(screen.getByRole("menuitemradio", { name: "Mörkt" }));
  await waitFor(() => expect(document.documentElement.classList.contains("dark")).toBe(true));
});
