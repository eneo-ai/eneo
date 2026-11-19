// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen } from "@testing-library/react";
import { useRef, useState } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { reportResize, setViewport } from "@/test/setup-dom";
import { CompanionLayout } from "./companion-layout";

afterEach(cleanup);

/**
 * A page with a toggle in its content and the aside's own close; with
 * `closable`, Escape may close the aside, which holds a field that takes
 * Escape for itself and a dialog.
 */
function Page({
  initiallyOpen = false,
  closable = false
}: {
  initiallyOpen?: boolean;
  closable?: boolean;
}) {
  const [open, setOpen] = useState(initiallyOpen);
  const toggle = useRef<HTMLButtonElement>(null);
  return (
    // The page's scroller, as main#main-content is in the app.
    <div data-testid="scroller" style={{ overflowY: "auto" }}>
      <CompanionLayout
        open={open}
        label="Hjälpen"
        contentLabel="Inställningarna"
        resizeLabel="Ändra hjälpens bredd"
        widthStorageKey="test:companion-width"
        returnFocus={() => toggle.current}
        onClose={closable ? () => setOpen(false) : undefined}
        aside={(presentation) => (
          <div>
            <p>Visas som {presentation}</p>
            <button type="button" onClick={() => setOpen(false)}>
              Stäng hjälpen
            </button>
            {closable ? (
              <>
                {/* A field whose open suggestions Escape closes, as a composer's "@" menu
                    does: it prevents the key's default, as Astryx's menus and layers do. */}
                <input
                  aria-label="Meddelande"
                  onKeyDown={(event) => {
                    if (event.key === "Escape") event.preventDefault();
                  }}
                />
                <dialog open>
                  <button type="button">Avbryt</button>
                </dialog>
              </>
            ) : null}
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
/** The box in the content that scrolls while the content has its own scroller. */
const scrollBox = () => content().firstElementChild as HTMLElement;
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

  describe("the content's own scroll beside the aside", () => {
    const view = () => screen.getByTestId("scroller");
    const contentRegion = () => screen.queryByRole("region", { name: "Inställningarna" });
    /** The page's scroller is 640 px tall. */
    const measureView = () => act(() => reportResize(view(), { width: 1200, height: 640 }));

    it("scrolls the content on its own, the row as tall as the view, while the aside is open beside it", () => {
      renderInApp(<Page />);
      measureRow(1200);
      measureView();
      openAside();

      expect(frame()?.dataset.companion).toBe("beside");
      expect(row().style.height).toBe("640px");
      expect(contentRegion()).toBe(scrollBox());
      expect(scrollBox().dataset.scrollAxis).toBe("block");
      expect(scrollBox().style.getPropertyValue("--x-overflowY")).toBe("auto");
    });

    it("leaves the page the scroller while the aside is closed, over the content or on a phone", () => {
      renderInApp(<Page />);
      measureRow(1200);
      measureView();
      const pageScrolls = () => {
        expect(row().style.height).toBe("");
        expect(contentRegion()).toBeNull();
        expect(scrollBox().hasAttribute("data-scroll-axis")).toBe(false);
        expect(scrollBox().style.getPropertyValue("--x-overflowY")).toBe("");
      };
      pageScrolls();

      openAside();
      fireEvent.click(screen.getByRole("button", { name: "Stäng hjälpen" }));
      pageScrolls();

      measureRow(700);
      openAside();
      expect(frame()?.dataset.companion).toBe("cover");
      pageScrolls();

      act(() => setViewport("phone"));
      expect(frame()?.dataset.companion).toBe("phone");
      pageScrolls();
    });

    it("keeps the content mounted as it starts and stops scrolling on its own", () => {
      renderInApp(<Page />);
      measureRow(1200);
      measureView();
      const field = screen.getByRole<HTMLInputElement>("textbox", { name: "Namn" });
      fireEvent.change(field, { target: { value: "Medborgarbrev" } });

      openAside();
      expect(contentRegion()).not.toBeNull();
      fireEvent.click(screen.getByRole("button", { name: "Stäng hjälpen" }));

      expect(screen.getByRole("textbox", { name: "Namn" })).toBe(field);
      expect(field.value).toBe("Medborgarbrev");
    });

    it("has no axe violations while the content scrolls on its own", async () => {
      const { container } = renderInApp(<Page />);
      measureRow(1200);
      measureView();
      openAside();
      expect(contentRegion()).not.toBeNull();
      await expectNoAxeViolations(container);
    });
  });

  describe("the person's place when the content's scroller changes", () => {
    /**
     * A settings page with a sticky header and three sections, laid out by
     * hand (jsdom has no layout): the view's top is at 100 px, the header
     * rests there 60 px tall, and the sections are taller once the aside
     * narrows the content (B starts at 600 px on the page, at 900 px beside
     * the aside). Each scroller's offset is kept here.
     */
    function layOutByHand() {
      const scrolled = { page: 650, content: 0 };
      const ownBox = scrollBox();
      const ownScroll = () => ownBox.getAttribute("role") === "region";
      const offset = () => (ownScroll() ? scrolled.content : scrolled.page);
      const box = (top: number, height: number) =>
        DOMRect.fromRect({ x: 0, y: top, width: 800, height });
      const scrollable = (element: HTMLElement, key: keyof typeof scrolled) =>
        Object.defineProperty(element, "scrollTop", {
          configurable: true,
          get: () => scrolled[key],
          set: (value: number) => (scrolled[key] = value)
        });
      scrollable(screen.getByTestId("scroller"), "page");
      scrollable(ownBox, "content");
      screen.getByTestId("scroller").getBoundingClientRect = () => box(100, 640);
      const sections = {
        a: [0, 600, 0, 900],
        b: [600, 1200, 900, 1700],
        c: [1200, 1800, 1700, 2500]
      };
      // The scroll box is the view while it scrolls, and as tall as what it holds otherwise.
      ownBox.getBoundingClientRect = () =>
        ownScroll() ? box(100, 640) : box(100 - offset(), 1800);
      (ownBox.firstElementChild as HTMLElement).getBoundingClientRect = () =>
        box(100 - offset(), ownScroll() ? 2500 : 1800);
      screen.getByTestId("sticky-header").getBoundingClientRect = () => box(100, 60);
      for (const [id, [start, end, startBeside, endBeside]] of Object.entries(sections)) {
        screen.getByTestId(`section-${id}`).getBoundingClientRect = () =>
          ownScroll()
            ? box(100 + startBeside! - offset(), endBeside! - startBeside!)
            : box(100 + start! - offset(), end! - start!);
      }
      return {
        scrolled,
        sectionTop: () => screen.getByTestId("section-b").getBoundingClientRect().top
      };
    }

    function SettingsPage() {
      const [open, setOpen] = useState(false);
      const toggle = useRef<HTMLButtonElement>(null);
      return (
        <div data-testid="scroller" style={{ overflowY: "auto" }}>
          <CompanionLayout
            open={open}
            label="Hjälpen"
            contentLabel="Inställningarna"
            resizeLabel="Ändra hjälpens bredd"
            widthStorageKey="test:companion-width"
            returnFocus={() => toggle.current}
            aside={() => (
              <button type="button" onClick={() => setOpen(false)}>
                Stäng hjälpen
              </button>
            )}
          >
            <header data-testid="sticky-header" style={{ position: "sticky" }}>
              <button ref={toggle} type="button" onClick={() => setOpen(true)}>
                Hjälp
              </button>
            </header>
            <section data-testid="section-a">Allmänt</section>
            <section data-testid="section-b">Funktioner</section>
            <section data-testid="section-c">Säkerhet</section>
          </CompanionLayout>
        </div>
      );
    }

    it("keeps the section being read where it was as the content starts scrolling on its own", () => {
      renderInApp(<SettingsPage />);
      measureRow(1200);
      act(() => reportResize(screen.getByTestId("scroller"), { width: 1200, height: 640 }));
      const { scrolled, sectionTop } = layOutByHand();
      // Funktioner starts 50 px down the view, under the header.
      expect(sectionTop()).toBe(50);

      openAside();
      expect(screen.getByRole("region", { name: "Inställningarna" })).toBe(scrollBox());
      expect(sectionTop()).toBe(50);
      expect(scrolled.content).toBe(950);
      // The page had nothing left to scroll meanwhile.
      scrolled.page = 0;

      fireEvent.click(screen.getByRole("button", { name: "Stäng hjälpen" }));
      expect(screen.queryByRole("region", { name: "Inställningarna" })).toBeNull();
      expect(sectionTop()).toBe(50);
      expect(scrolled.page).toBe(650);
    });
  });

  describe("Escape", () => {
    const pressEscape = (target: Element) =>
      fireEvent.keyDown(target, { key: "Escape", bubbles: true, cancelable: true });

    it("closes an aside over the content, focus back on the toggle", () => {
      renderInApp(<Page closable />);
      measureRow(700);
      const toggle = screen.getByRole("button", { name: "Hjälp" });
      toggle.focus();
      openAside();
      expect(frame()?.dataset.companion).toBe("cover");

      pressEscape(screen.getByRole("button", { name: "Stäng hjälpen" }));
      expect(frame()?.hidden).toBe(true);
      expect(document.activeElement).toBe(toggle);
      expect(content().hasAttribute("inert")).toBe(false);
    });

    it("closes the aside on a phone too", () => {
      setViewport("phone");
      renderInApp(<Page closable />);
      measureRow(1200);
      openAside();
      pressEscape(region()!);
      expect(frame()?.hidden).toBe(true);
    });

    it("leaves an aside beside the content open", () => {
      renderInApp(<Page closable />);
      measureRow(1200);
      openAside();
      pressEscape(screen.getByRole("button", { name: "Stäng hjälpen" }));
      expect(frame()?.hidden).toBe(false);
    });

    it("first leaves an Escape that something in the aside acted on to it, and closes on the next", () => {
      renderInApp(<Page closable />);
      measureRow(700);
      openAside();
      pressEscape(screen.getByRole("textbox", { name: "Meddelande" }));
      expect(frame()?.hidden).toBe(false);

      pressEscape(screen.getByRole("button", { name: "Stäng hjälpen" }));
      expect(frame()?.hidden).toBe(true);
    });

    it("leaves an Escape in a dialog to the dialog", () => {
      renderInApp(<Page closable />);
      measureRow(700);
      openAside();
      pressEscape(screen.getByRole("button", { name: "Avbryt" }));
      expect(frame()?.hidden).toBe(false);
    });

    it("does nothing where the page gives no way to close it", () => {
      renderInApp(<Page />);
      measureRow(700);
      openAside();
      pressEscape(screen.getByRole("button", { name: "Stäng hjälpen" }));
      expect(frame()?.hidden).toBe(false);
    });
  });
});
