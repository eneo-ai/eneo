// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { renderInApp } from "@/test/render";
import { PageBar } from "./page-bar";

afterEach(cleanup);

const bar = () => document.querySelector<HTMLElement>("[data-page-bar], [data-phone-page-bar]")!;

describe("PageBar", () => {
  it("replaces the shell's top bar below 1024 px by default", () => {
    renderInApp(<PageBar parent={{ label: "Administration", href: "/admin" }} />);
    expect(bar().hasAttribute("data-own-mobile-header")).toBe(true);
    expect(bar().hasAttribute("data-page-bar")).toBe(true);
    expect(bar().className).toContain("lg:hidden");
    expect(screen.getByRole("link", { name: "Tillbaka till Administration" })).toBeTruthy();
  });

  it("replaces it on phones only for a space, which tablets show under the top bar", () => {
    renderInApp(<PageBar until="md" parent={{ label: "Ytor", href: "/spaces/list" }} />);
    expect(bar().hasAttribute("data-own-phone-header")).toBe(true);
    expect(bar().hasAttribute("data-own-mobile-header")).toBe(false);
    expect(bar().hasAttribute("data-phone-page-bar")).toBe(true);
    expect(bar().className).toContain("md:hidden");
    expect(bar().className).not.toContain("lg:hidden");
  });

  it("keeps the back link's side at 44 px however much room the title and action ask for", () => {
    renderInApp(
      <PageBar until="md" parent={{ label: "Assistenter", href: "/spaces/1/assistants" }} />
    );
    // jsdom has no layout, so the track is asserted as its class. At 320 px a 160 px title and
    // an icon-and-text action left the back side about 44 px: CI measured it under the contract.
    expect(bar().className).toContain("grid-cols-[minmax(2.75rem,1fr)_");
  });
});
