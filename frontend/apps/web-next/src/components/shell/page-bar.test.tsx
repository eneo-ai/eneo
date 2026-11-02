// @vitest-environment jsdom
import { act, cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { reportResize } from "@/test/setup-dom";
import { PageBar } from "./page-bar";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

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
    renderInApp(<PageBar until="phone" parent={{ label: "Ytor", href: "/spaces/list" }} />);
    expect(bar().hasAttribute("data-own-phone-header")).toBe(true);
    expect(bar().hasAttribute("data-own-mobile-header")).toBe(false);
    expect(bar().hasAttribute("data-phone-page-bar")).toBe(true);
    // A phone held either way: hidden only where the layout is not a phone's.
    expect(bar().className).toContain("wide:hidden");
    expect(bar().className).not.toContain("lg:hidden");
  });

  it("keeps the back link's side at 44 px however much room the title and action ask for", () => {
    renderInApp(
      <PageBar until="phone" parent={{ label: "Assistenter", href: "/spaces/1/assistants" }} />
    );
    // jsdom has no layout, so the track is asserted as its class. At 320 px a 160 px title and
    // an icon-and-text action left the back side about 44 px: CI measured it under the contract.
    expect(bar().className).toContain("grid-cols-[minmax(2.75rem,max-content)_");
  });

  it.each([90, 20])("names the parent however little room the back link has (%i px)", (width) => {
    // Every label measures wider than the side, as "Administration" beside a title at 390 px.
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      measureText: () => ({ width: 500 })
    } as unknown as CanvasRenderingContext2D);
    renderInApp(
      <PageBar
        parent={{ label: "Administration", href: "/admin" }}
        title="Inloggning (SSO)"
        isTitleShown
      />
    );
    const link = screen.getByRole("link", { name: "Tillbaka till Administration" });
    const cell = link.parentElement!;
    Object.defineProperty(cell, "clientWidth", { value: width });
    act(() => reportResize(cell, { width }));
    // The link's text truncates with an ellipsis instead (the label's own CSS).
    expect(link.textContent).toBe("Administration");
  });
});
