// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { Button, buttonVariants } from "./button";
import { Checkbox } from "./checkbox";
import { Input } from "./input";
import { Label } from "./label";
import { RadioGroup, RadioGroupItem } from "./radio-group";
import { Select, SelectTrigger, SelectValue } from "./select";
import { Switch } from "./switch";
import { Tabs, TabsContent, TabsList, TabsTrigger, tabsListVariants } from "./tabs";
import { Textarea } from "./textarea";
import { AlertDescription } from "./alert";

/*
 * The legacy shadcn controls meet WCAG 2.2 AA like the Astryx ones
 * (ACCESSIBILITY.md): a full-strength 3:1 focus ring instead of the 50% halo,
 * hover tints that keep the label's contrast, 24 px targets and 44 px on a
 * coarse pointer. jsdom has no layout, so the classes that draw them are the
 * contract; the colours are checked in eneo-theme.contrast.test.ts and the
 * lint rule eneo/no-weak-focus-indicator keeps translucent rings out.
 */

afterEach(cleanup);

const VARIANTS = ["default", "destructive", "outline", "secondary", "ghost", "link"] as const;
const SIZES = ["default", "xs", "sm", "lg", "icon", "icon-xs", "icon-sm", "icon-lg"] as const;

const classesOf = (element: Element) => element.getAttribute("class")?.split(/\s+/) ?? [];

function expectFocusRing(element: Element) {
  const classes = classesOf(element);
  expect(classes).toContain("focus-visible:outline-2");
  expect(classes.some((name) => /^focus-visible:outline-(ring|destructive)$/.test(name))).toBe(
    true
  );
  expect(classes.join(" ")).not.toMatch(/ring-ring\/|(^|\s)outline-none(\s|$)/);
}

describe("Button", () => {
  it.each(VARIANTS)("%s draws the full-strength focus ring", (variant) => {
    render(<Button variant={variant}>Spara</Button>);
    expectFocusRing(screen.getByRole("button", { name: "Spara" }));
  });

  it.each(["default", "destructive", "secondary"] as const)(
    "%s hovers with the overlay instead of a faded fill",
    (variant) => {
      const classes = buttonVariants({ variant }).split(" ");
      expect(classes).toContain("hover:bg-ax-hover-overlay");
      expect(classes.join(" ")).not.toMatch(/hover:bg-[\w-]+\/\d+/);
    }
  );

  it("uses the on-colour tokens and the 4.5:1 accent text token", () => {
    expect(buttonVariants({ variant: "destructive" })).toContain("text-destructive-foreground");
    expect(buttonVariants({ variant: "destructive" })).not.toContain("text-white");
    expect(buttonVariants({ variant: "link" })).toContain("text-ax-text-accent");
  });

  it.each(SIZES)("%s is at least 44 px on a coarse pointer", (size) => {
    const classes = buttonVariants({ size }).split(" ");
    expect(classes).toContain("pointer-coarse:min-h-11");
    if (size.startsWith("icon")) expect(classes).toContain("pointer-coarse:min-w-11");
  });

  it("shows a busy button's state with a spinner, and keeps it enabled", async () => {
    const { container, rerender } = render(<Button aria-busy>Spara</Button>);
    const button = screen.getByRole("button", { name: "Spara" });
    expect(button.hasAttribute("disabled")).toBe(false);
    expect(classesOf(button)).toContain("cursor-progress");
    expect(button.querySelector("svg[aria-hidden='true']")).not.toBeNull();
    await expectNoAxeViolations(container);

    rerender(<Button>Spara</Button>);
    expect(button.querySelector("svg")).toBeNull();
    expect(classesOf(button)).not.toContain("cursor-progress");
  });

  it("adds no spinner to a busy icon button, which has no room for it", () => {
    render(
      <Button size="icon" aria-label="Uppdatera" aria-busy>
        ↻
      </Button>
    );
    expect(screen.getByRole("button", { name: "Uppdatera" }).querySelector("svg")).toBeNull();
  });

  it("ignores a press while busy and acts on one when idle", () => {
    const onClick = vi.fn();
    const { rerender } = render(
      <Button aria-busy onClick={onClick}>
        Spara
      </Button>
    );
    fireEvent.click(screen.getByRole("button", { name: "Spara" }));
    expect(onClick).not.toHaveBeenCalled();

    rerender(<Button onClick={onClick}>Spara</Button>);
    fireEvent.click(screen.getByRole("button", { name: "Spara" }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("ignores a press on a busy icon button, which shows no spinner", () => {
    const onClick = vi.fn();
    render(
      <Button size="icon" aria-label="Stoppa inspelning" aria-busy="true" onClick={onClick}>
        ■
      </Button>
    );
    fireEvent.click(screen.getByRole("button", { name: "Stoppa inspelning" }));
    expect(onClick).not.toHaveBeenCalled();
  });

  it("ignores a press on a busy composed (asChild) button, and passes one through when idle", () => {
    const onChildClick = vi.fn();
    const composed = (busy: boolean) => (
      <Button asChild aria-busy={busy || undefined}>
        <button type="button" onClick={onChildClick}>
          Spara
        </button>
      </Button>
    );
    const { rerender } = render(composed(true));
    fireEvent.click(screen.getByRole("button", { name: "Spara" }));
    expect(onChildClick).not.toHaveBeenCalled();

    rerender(composed(false));
    fireEvent.click(screen.getByRole("button", { name: "Spara" }));
    expect(onChildClick).toHaveBeenCalledTimes(1);
  });

  it("does not submit its form while busy", () => {
    const onSubmit = vi.fn((event: React.SubmitEvent) => event.preventDefault());
    render(
      <form onSubmit={onSubmit}>
        <Button type="submit" aria-busy>
          Skicka
        </Button>
      </form>
    );
    fireEvent.click(screen.getByRole("button", { name: "Skicka" }));
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("is a named, focusable button", async () => {
    const { container } = render(
      <Button size="icon" aria-label="Stäng">
        ×
      </Button>
    );
    const button = screen.getByRole("button", { name: "Stäng" });
    button.focus();
    expect(document.activeElement).toBe(button);
    await expectNoAxeViolations(container);
  });
});

describe("form controls", () => {
  function Form() {
    return (
      <form>
        <Label htmlFor="name">Namn</Label>
        <Input id="name" />
        <Label htmlFor="notes">Anteckningar</Label>
        <Textarea id="notes" />
        <Select defaultValue="a">
          <SelectTrigger aria-label="Modell">
            <SelectValue />
          </SelectTrigger>
        </Select>
        <Label>
          <Checkbox /> Påminn mig
        </Label>
        <RadioGroup aria-label="Synlighet" defaultValue="all">
          <Label>
            <RadioGroupItem value="all" /> Alla
          </Label>
        </RadioGroup>
        <Label>
          <Switch /> Aktiv
        </Label>
        <Tabs defaultValue="one">
          <TabsList>
            <TabsTrigger value="one">Ett</TabsTrigger>
            <TabsTrigger value="two">Två</TabsTrigger>
          </TabsList>
          <TabsContent value="one">Första fliken</TabsContent>
          <TabsContent value="two">Andra fliken</TabsContent>
        </Tabs>
      </form>
    );
  }

  it("show the full-strength ring and take keyboard focus", async () => {
    const { container } = render(<Form />);
    const controls = [
      screen.getByRole("textbox", { name: "Namn" }),
      screen.getByRole("textbox", { name: "Anteckningar" }),
      screen.getByRole("combobox", { name: "Modell" }),
      screen.getByRole("checkbox", { name: "Påminn mig" }),
      screen.getByRole("radio", { name: "Alla" }),
      screen.getByRole("switch", { name: "Aktiv" }),
      screen.getByRole("tab", { name: "Ett" }),
      // Radix puts the panel in the tab order (tabIndex 0).
      screen.getByRole("tabpanel", { name: "Ett" })
    ];
    for (const control of controls) {
      expectFocusRing(control);
      control.focus();
      expect(document.activeElement).toBe(control);
    }
    await expectNoAxeViolations(container);
  });

  it("are 44 px on a coarse pointer (checkbox, radio and switch through a larger hit area)", () => {
    render(<Form />);
    for (const name of ["Namn", "Modell"] as const) {
      const control =
        name === "Namn"
          ? screen.getByRole("textbox", { name })
          : screen.getByRole("combobox", { name });
      expect(classesOf(control)).toContain("pointer-coarse:min-h-11");
    }
    // A short label (Kör, Run) leaves a tab under 44 px wide unless it has a floor.
    expect(classesOf(screen.getByRole("tab", { name: "Ett" }))).toEqual(
      expect.arrayContaining(["pointer-coarse:min-h-11", "pointer-coarse:min-w-11"])
    );
    for (const control of [
      screen.getByRole("checkbox", { name: "Påminn mig" }),
      screen.getByRole("radio", { name: "Alla" }),
      screen.getByRole("switch", { name: "Aktiv" })
    ]) {
      const classes = classesOf(control);
      expect(classes).toContain("relative");
      expect(classes).toContain("after:absolute");
    }
    // The 16 px checkbox and radio have a 1 px border, so a fixed -inset-3.5
    // gave 14 + 28 = 42 px: the hit area is a 24 / 44 px box centred on them.
    for (const control of [
      screen.getByRole("checkbox", { name: "Påminn mig" }),
      screen.getByRole("radio", { name: "Alla" })
    ]) {
      expect(classesOf(control)).toEqual(
        expect.arrayContaining([
          "after:inset-[calc(50%-12px)]",
          "pointer-coarse:after:inset-[calc(50%-22px)]"
        ])
      );
    }
    expect(
      classesOf(screen.getByRole("switch", { name: "Aktiv" })).some((name) =>
        name.startsWith("pointer-coarse:after:-inset")
      )
    ).toBe(true);
  });
});

describe("TabsList", () => {
  // A centred list too narrow for its tabs overflows on both sides, and what
  // lies before the scroll origin cannot be scrolled to (the first state tab on
  // the admin API keys page at 320 px). jsdom has no layout: the class is the
  // contract; tests/responsive-measure.spec.ts shows the overflow it causes.
  it("starts its tabs, so an overflowing list scrolls to every one", () => {
    expect(tabsListVariants().split(" ")).not.toContain("justify-center");
  });

  // flex-1 shared the list's width equally: on touch (min-w-11 replaces the
  // automatic minimum) a long label spilled onto the tab beside it.
  it("makes each tab at least as wide as its label", () => {
    render(
      <Tabs defaultValue="tokens">
        <TabsList>
          <TabsTrigger value="tokens">Tokens</TabsTrigger>
          <TabsTrigger value="users">Användare</TabsTrigger>
        </TabsList>
      </Tabs>
    );
    const classes = classesOf(screen.getByRole("tab", { name: "Användare" }));
    expect(classes).toContain("flex-[1_0_auto]");
    expect(classes).not.toContain("flex-1");
  });
});

describe("AlertDescription", () => {
  // Its grid puts a link on a row of its own, so the link is no inline text link.
  it("gives a link in it a 44 px row on a coarse pointer", () => {
    render(
      <AlertDescription>
        Det finns inga nycklar. <a href="/admin/api-keys">Hantera API-nycklar</a>
      </AlertDescription>
    );
    const classes = classesOf(
      screen.getByRole("link", { name: "Hantera API-nycklar" }).parentElement!
    );
    expect(classes).toContain("pointer-coarse:[&>a]:min-h-11");
    expect(classes).toContain("pointer-coarse:[&>a]:items-center");
  });
});
