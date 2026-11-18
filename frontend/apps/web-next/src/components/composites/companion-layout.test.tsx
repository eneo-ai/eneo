// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen } from "@testing-library/react";
import { useRef, useState } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { reportResize, setViewport } from "@/test/setup-dom";
import { CompanionLayout } from "./companion-layout";

afterEach(cleanup);

/** A page with a toggle in its content and the aside's own close. */
function Page({ initiallyOpen = false }: { initiallyOpen?: boolean }) {
  const [open, setOpen] = useState(initiallyOpen);
  const toggle = useRef<HTMLButtonElement>(null);
  return (
    // The page's scroller, as main#main-content is in the app.
    <div data-testid="scroller" style={{ overflowY: "auto" }}>
      <CompanionLayout
        open={open}
        label="Hjälpen"
        resizeLabel="Ändra hjälpens bredd"
        widthStorageKey="test:companion-width"
        returnFocus={() => toggle.current}
        aside={(presentation) => (
          <div>
            <p>Visas som {presentation}</p>
            <button type="button" onClick={() => setOpen(false)}>
              Stäng hjälpen
            </button>
          </div>
        )}
      >
        <h1>Inställningar</h1>
        <button ref={toggle} type="button" aria-pressed={open} onClick={() => setOpen(!open)}>
          Hjälp
        </button>
        <label>
          Namn <input />
        </label>
      </CompanionLayout>
    </div>
  );
}

const row = () => document.querySelector<HTMLElement>("[data-companion-row]")!;
const content = () => row().firstElementChild as HTMLElement;
const frame = () => document.querySelector<HTMLElement>("[data-companion]");
const region = () => screen.queryByRole("complementary", { name: "Hjälpen" });

function measureRow(width: number) {
  act(() => reportResize(row(), { width, height: 2000 }));
}

function openAside() {
  fireEvent.click(screen.getByRole("button", { name: "Hjälp" }));
}

describe("CompanionLayout", () => {
  it("keeps the aside out of the page until it first opens, then keeps it while closed", () => {
    renderInApp(<Page />);
    measureRow(1200);
    expect(region()).toBeNull();

    openAside();
    expect(region()).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Stäng hjälpen" }));

    // Kept with what it holds, out of view and out of the accessibility tree.
    expect(frame()?.hidden).toBe(true);
    expect(screen.getByText("Visas som beside", { selector: "p" })).toBeTruthy();
  });

  it("sits beside the content, with a handle, where the row leaves the content 480 px", () => {
    renderInApp(<Page />);
    measureRow(1200);
    openAside();

    expect(frame()?.dataset.companion).toBe("beside");
    expect(screen.getByRole("separator", { name: "Ändra hjälpens bredd" })).toBeTruthy();
    expect(screen.getByText("Visas som beside")).toBeTruthy();
    expect(content().hasAttribute("inert")).toBe(false);
  });

  it("covers the content where the row has no room, and the content is inert while it does", () => {
    renderInApp(<Page />);
    measureRow(800);
    openAside();

    expect(frame()?.dataset.companion).toBe("cover");
    expect(screen.queryByRole("separator")).toBeNull();
    expect(screen.getByText("Visas som cover")).toBeTruthy();
    expect(content().hasAttribute("inert")).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Stäng hjälpen" }));
    expect(content().hasAttribute("inert")).toBe(false);
  });

  it("covers the whole screen on a phone, however wide the row, and says so to the aside", () => {
    setViewport("phone");
    renderInApp(<Page />);
    measureRow(1200);
    openAside();

    expect(frame()?.dataset.companion).toBe("phone");
    expect(screen.getByText("Visas som phone")).toBeTruthy();
    expect(content().hasAttribute("inert")).toBe(true);
  });

  it("moves focus into the aside when it opens and back to the toggle when it closes", () => {
    renderInApp(<Page />);
    measureRow(1200);
    const toggle = screen.getByRole("button", { name: "Hjälp" });
    toggle.focus();
    openAside();

    expect(document.activeElement).toBe(region());
    fireEvent.click(screen.getByRole("button", { name: "Stäng hjälpen" }));
    expect(document.activeElement).toBe(toggle);
  });

  it("takes the focus the content had when it comes to cover the content", () => {
    renderInApp(<Page />);
    measureRow(1200);
    openAside();
    const field = screen.getByRole("textbox", { name: "Namn" });
    field.focus();

    measureRow(700);
    expect(frame()?.dataset.companion).toBe("cover");
    expect(document.activeElement).toBe(region());
  });

  it("is as tall as the view the page scrolls in, so it stays in view", () => {
    renderInApp(<Page />);
    measureRow(1200);
    openAside();
    act(() => reportResize(screen.getByTestId("scroller"), { width: 1200, height: 640 }));

    expect(frame()?.style.height).toBe("640px");
  });

  it("has no axe violations beside the content or over it", async () => {
    const { container } = renderInApp(<Page />);
    measureRow(1200);
    openAside();
    await expectNoAxeViolations(container);

    measureRow(700);
    await expectNoAxeViolations(container);
  });
});
