// @vitest-environment jsdom
import { Link } from "@astryxdesign/core/Link";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { ThemeProvider } from "next-themes";
import { describe, expect, it } from "vitest";
import { renderInApp } from "@/test/render";
import { AstryxProvider } from "./astryx-provider";

describe("AstryxProvider", () => {
  it("renders Astryx links with next/link and without Astryx's router prop `to`", () => {
    renderInApp(<Link href="/spaces/list">Ytor</Link>);

    const link = screen.getByRole("link", { name: "Ytor" });
    expect(link.getAttribute("href")).toBe("/spaces/list");
    expect(link.hasAttribute("to")).toBe(false);
  });

  it("keeps Astryx on the system mode whatever next-themes resolves", () => {
    // A mode that changed after hydration would change Theme's context:
    // every Astryx component would re-render, and a streamed page not yet
    // revealed would be client-rendered. The colour follows next-themes'
    // class on <html> through globals.css instead.
    const { container } = render(
      <ThemeProvider attribute="class" forcedTheme="dark">
        <NextIntlClientProvider locale="sv" messages={{}}>
          <AstryxProvider>
            <p>Innehåll</p>
          </AstryxProvider>
        </NextIntlClientProvider>
      </ThemeProvider>
    );

    const wrapper = container.querySelector("[data-astryx-theme]");
    expect(wrapper).not.toBeNull();
    expect(wrapper?.hasAttribute("data-theme")).toBe(false);
  });
});
