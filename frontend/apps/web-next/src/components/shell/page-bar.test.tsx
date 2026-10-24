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
});
