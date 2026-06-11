// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { expect, it } from "vitest";
import { ThemeSwitcher } from "./theme-switcher";

const messages = { theme: "Tema", light: "Ljust", dark: "Mörkt", system: "System" };

it("renders the theme menu trigger", () => {
  render(
    <NextIntlClientProvider locale="sv" messages={messages}>
      <ThemeSwitcher />
    </NextIntlClientProvider>
  );
  expect(screen.getByRole("button", { name: "Tema" })).toBeDefined();
});
